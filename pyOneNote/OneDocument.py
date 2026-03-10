import re
import hashlib
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from pyOneNote.Header import Header
from pyOneNote.FileNode import (
    FileNodeList,
    FileDataStoreObjectReferenceFND,
    ObjectDeclarationFileData3RefCountFND,
    ReadOnlyObjectDeclaration2RefCountFND,
    ReadOnlyObjectDeclaration2LargeRefCountFND,
)

logger = logging.getLogger(__name__)

# 자동 하이퍼링크 탐지를 위한 URL 패턴 (OneNote가 텍스트를 자동으로 하이퍼링크로 변환하는 경우)
_AUTO_HYPERLINK_PATTERN = re.compile(
    r'(https?://\S+|ftp://\S+|www\.\S+)',
    re.IGNORECASE,
)


def get_next_node_identity(fileNodes, node):
    found = False
    for current in fileNodes:
        if found:
            return current
        if current is node:
            found = True
    return None


def get_previous_node_identity(fileNodes, node):
    prev = None
    for current in fileNodes:
        if current is node:
            return prev
        prev = current
    return None

class OneDocument:
    def __init__(self, fh_onenote, debug=False):
        self.debug = debug
        self._files = None
        self._properties= None
        self._links: Optional[List[Dict[str, str]]] = None
        self._global_identification_table= {}
        self.cur_revision = None
        self.header = None
        self.container = None
        self.root_file_node_list = None
        self.fh_onenote = fh_onenote

    def parse(self):
        self.header = Header(self.fh_onenote, debug=self.debug)
        self.root_file_node_list = FileNodeList(self.fh_onenote, self, self.header.fcrFileNodeListRoot, self)

    @staticmethod
    def traverse_nodes(root_file_node_list, nodes, filters):
        for fragment in root_file_node_list.fragments:
            for file_node in fragment.fileNodes:
                if len(filters) == 0 or hasattr(file_node, "data") and type(file_node.data).__name__ in filters:
                    nodes.append(file_node)

                for child_file_node_list in file_node.children:
                    OneDocument.traverse_nodes(child_file_node_list, nodes, filters)

    def get_properties(self):
        if self._properties:
            return self._properties
        nodes = []
        filters = ['ObjectDeclaration2RefCountFND']

        self._properties = []

        OneDocument.traverse_nodes(self.root_file_node_list, nodes, filters)
        for node in nodes:
            if hasattr(node, 'propertySet') and node.propertySet:
                node.propertySet.body.indent= '\t\t'
                self._properties.append({'type': str(node.data.body.jcid), 'type_id': node.data.body.jcid.jcid,'identity':str(node.data.body.oid), 'val':node.propertySet.body.get_properties()})

        return  self._properties

    @staticmethod
    def _get_node_body(node):
        """ReadOnly 타입은 data.base.body 경로, 일반 타입은 data.body 경로로 body를 반환한다."""
        if isinstance(node.data, (ReadOnlyObjectDeclaration2RefCountFND,
                                  ReadOnlyObjectDeclaration2LargeRefCountFND)):
            return node.data.base.body
        return node.data.body

    @staticmethod
    def _get_props_text(props: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """MS-ONE 2.2.23: RichEditTextUnicode가 우선, 없으면 TextExtendedAscii를 사용한다.

        Returns:
            (rich_text, text_source) 튜플. 텍스트가 없으면 (None, None).
        """
        for key in ('RichEditTextUnicode', 'TextExtendedAscii'):
            value = props.get(key)
            if value and isinstance(value, str):
                return value, key
        return None, None

    @staticmethod
    def _build_text_formatting(
        props: Dict[str, Any],
        oid_to_props: Dict[str, Any],
    ) -> List[Any]:
        """TextRunFormatting 참조를 실제 properties로 치환한 리스트를 반환한다."""
        return [
            oid_to_props.get(ref, ref)
            for ref in props.get('TextRunFormatting', [])
        ]

    @staticmethod
    def _extract_explicit_hyperlink(
        rich_text: str,
        body,
        text_source: str,
        props: Dict[str, Any],
        oid_to_props: Dict[str, Any],
        property_set_body=None,
    ) -> Optional[Dict[str, Any]]:
        """패턴 1: 명시적 하이퍼링크 — \\ufddfHYPERLINK "URL" FriendlyName 추출.

        매칭되지 않으면 None을 반환한다.
        """
        match = re.search(r'\ufddfHYPERLINK\s+"([^"]+)"\s*(.*?)[\x00]?$', rich_text)
        if not match:
            return None

        url = match.group(1)
        display_text = match.group(2)
        logger.debug(
            "type: %s, identity: %s, properties: %s",
            body.jcid, body.oid, props,
        )
        if property_set_body is not None:
            logger.debug(
                "url: %s, display_text: %s, source: %s, pos: %s",
                url, display_text, text_source,
                property_set_body.get_property_pos(text_source),
            )

        return {
            'type': str(body.jcid),
            'url': url,
            'display_text': display_text,
            'source': text_source,
            'full_text': rich_text,
            # 'text_formatting': OneDocument._build_text_formatting(props, oid_to_props),
        }

    @staticmethod
    def _extract_auto_hyperlinks(
        rich_text: str,
        body,
        text_source: str,
        props: Dict[str, Any],
        oid_to_props: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """패턴 2: 자동 하이퍼링크 — 텍스트 내 URL 패턴 탐지.

        OneNote가 "www.google.com" 등을 자동으로 하이퍼링크로 변환한 경우를 처리한다.
        """
        results: List[Dict[str, Any]] = []
        text_formatting = OneDocument._build_text_formatting(props, oid_to_props)

        for auto_url in _AUTO_HYPERLINK_PATTERN.findall(rich_text):
            # 후행 null 문자 제거
            auto_url = auto_url.rstrip('\x00')
            if not auto_url:
                continue

            logger.debug(
                "type: %s, identity: %s, properties: %s",
                body.jcid, body.oid, props,
            )
            logger.debug("auto-hyperlink url: %s, source: %s", auto_url, text_source)

            results.append({
                'type': str(body.jcid),
                'url': auto_url,
                'display_text': auto_url,
                'source': text_source,
                'full_text': rich_text,
                # 'text_formatting': text_formatting,
            })

        return results

    def get_links(self, include_text_urls: bool = True) -> List[Dict[str, str]]:
        if self._links is not None:
            return self._links

        self._links = []
        nodes: List[Any] = []
        filters = [
            'ObjectDeclaration2RefCountFND',
            'ReadOnlyObjectDeclaration2RefCountFND',
            'ReadOnlyObjectDeclaration2LargeRefCountFND',
        ]

        self._properties = []

        OneDocument.traverse_nodes(self.root_file_node_list, nodes, filters)

        # oid(ExtendedGUID 문자열) → 해당 객체의 properties 룩업 테이블
        oid_to_props: Dict[str, Any] = {}
        for node in nodes:
            if hasattr(node, 'propertySet') and node.propertySet:
                oid_str = str(self._get_node_body(node).oid)
                oid_to_props[oid_str] = node.propertySet.body.get_properties()

        for node in nodes:
            if not hasattr(node, 'propertySet') or not node.propertySet:
                continue

            body = self._get_node_body(node)
            props = node.propertySet.body.get_properties()

            # 텍스트에서 하이퍼링크 추출
            props_text, text_source = self._get_props_text(props)
            if props_text:
                link = self._extract_explicit_hyperlink(
                    props_text, body, text_source, props, oid_to_props,
                    property_set_body=node.propertySet.body,
                )
                if link:
                    self._links.append(link)
                else:
                    self._links.extend(
                        self._extract_auto_hyperlinks(
                            props_text, body, text_source, props, oid_to_props,
                        )
                    )

            # WzHyperlinkUrl 프로퍼티에서 하이퍼링크 추출
            wz_hyperlink_url = props.get('WzHyperlinkUrl')
            if wz_hyperlink_url:
                if isinstance(wz_hyperlink_url, str):
                    wz_hyperlink_url = wz_hyperlink_url.rstrip('\x00')
                logger.debug(
                    "type: %s, identity: %s, properties: %s",
                    body.jcid, body.oid, props,
                )
                logger.debug("WzHyperlinkUrl: %s", wz_hyperlink_url)
                self._links.append({
                    'type': str(body.jcid),
                    'url': wz_hyperlink_url,
                    'display_text': wz_hyperlink_url,
                    'source': 'WzHyperlinkUrl',
                    'full_text': wz_hyperlink_url,
                })

        return self._links


    def get_files(self):
        if self._files:
            return self._files
        nodes = []
        self._files = {}
        filters = ["FileDataStoreObjectReferenceFND", "ObjectDeclarationFileData3RefCountFND"]

        OneDocument.traverse_nodes(self.root_file_node_list, nodes, filters)

        self.get_global_identification_table()

        for node in nodes:
            if hasattr(node, "data") and node.data:
                if isinstance(node.data, FileDataStoreObjectReferenceFND):
                    if not str(node.data.guidReference) in self._files:
                        self._files[str(node.data.guidReference)] = {"extension": "", "content": "", "identity": ""}
                    self._files[str(node.data.guidReference)]["content"] = node.data.fileDataStoreObject.FileData
                elif isinstance(node.data, ObjectDeclarationFileData3RefCountFND):
                    guid = node.data.FileDataReference.StringData.replace("<ifndf>{", "").replace("}", "")
                    guid = guid.lower()
                    if not guid in self._files:
                        self._files[guid] = {"extension": "", "content": "", "identity": ""}
                    self._files[guid]["extension"] = node.data.Extension.StringData
                    self._files[guid]["identity"] = str(node.data.oid)
        return self._files


    def get_global_identification_table(self):
        return self._global_identification_table

    def get_json(
        self,
        include_sections: Optional[Set[str]] = None,
        files_include_content: bool = True,
    ) -> Dict[str, Any]:
        supported_sections = {"headers", "properties", "links", "files"}
        if include_sections is not None:
            unknown_sections = include_sections - supported_sections
            if unknown_sections:
                supported_str = ", ".join(sorted(supported_sections))
                unknown_str = ", ".join(sorted(unknown_sections))
                raise ValueError(
                    f"Unsupported include_sections value(s): {unknown_str}. Supported sections: {supported_str}"
                )

        if include_sections is None:
            active_sections = supported_sections
        else:
            active_sections = include_sections

        res: Dict[str, Any] = {}
        if "headers" in active_sections:
            res["headers"] = self.header.convert_to_dictionary()

        if "properties" in active_sections:
            res["properties"] = self.get_properties()

        if "links" in active_sections:
            res["links"] = self.get_links()

        if "files" in active_sections:
            files_json: Dict[str, Dict[str, str]] = {}
            for key, file_entry in self.get_files().items():
                extension = str(file_entry.get("extension", ""))
                identity = str(file_entry.get("identity", ""))
                raw_content = file_entry.get("content", b"")
                if isinstance(raw_content, (bytes, bytearray)):
                    content_bytes = bytes(raw_content)
                else:
                    content_bytes = b""

                key_str = str(key)
                if files_include_content:
                    files_json[key_str] = {
                        "extension": extension,
                        "content": content_bytes.hex(),
                        "identity": identity,
                    }
                else:
                    files_json[key_str] = {
                        "extension": extension,
                        "identity": identity,
                        "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
                    }

            res["files"] = files_json

        return res

    def __str__(self):
        return '{}\n{}\n{}'.format(str(self.header),
                                   str(self.rootFileNode))



