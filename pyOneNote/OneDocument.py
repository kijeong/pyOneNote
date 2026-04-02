import re
import hashlib
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from .Header import Header
from .FileNode import (
    FileNodeList,
    FileDataStoreObjectReferenceFND,
    ObjectDeclarationFileData3RefCountFND,
    ReadOnlyObjectDeclaration2RefCountFND,
    ReadOnlyObjectDeclaration2LargeRefCountFND,
)

logger = logging.getLogger(__name__)

# 자동 하이퍼링크 탐지를 위한 URL 패턴 (OneNote가 텍스트를 자동으로 하이퍼링크로 변환하는 경우)
_AUTO_HYPERLINK_PATTERN = re.compile(
    r'(https?://\S+|ftp://\S+|ftps?://\S+|onenote:\S+|mailto:\S+|file:///\S+|tel:\S+|ssh://\S+|www\.\S+)',
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
        filters = ['ObjectDeclaration2RefCountFND',
                   'ReadOnlyObjectDeclaration2RefCountFND',
                   'ReadOnlyObjectDeclaration2LargeRefCountFND']

        self._properties = []

        OneDocument.traverse_nodes(self.root_file_node_list, nodes, filters)
        for node in nodes:
            if hasattr(node, 'propertySet') and node.propertySet:
                node.propertySet.body.indent= '\t\t'
                body = self._get_node_body(node)
                self._properties.append({'type': str(body.jcid), 'type_id': body.jcid.jcid,'identity':str(body.oid), 'val':node.propertySet.body.get_properties()})

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

    def display(self):
        """root_file_node_list의 전체 FileNode 트리를 Composite 패턴으로 출력한다.

        출력 예시::

            [DISPLAY] OneDocument tree:
            └─ FileNodeList [0x00000410:0x00001000]
               └─ FileNodeListFragment [0x00000410:0x00001000] ID=1 Seq=0
                  ├─ [0x00000420:0x0000042B] ObjectSpaceManifestListReferenceFND 2
                  │  └─ FileNodeList [0x00001178:0x00001800]
                  │     └─ FileNodeListFragment [0x00001178:0x00001800] ID=2 Seq=0
                  │        ├─ [0x00001188:0x000011A0] ObjectSpaceManifestListStartFND 0
                  │        ├─ [0x000011A0:0x000011A7] RevisionManifestListReferenceFND 2
                  │        │  └─ FileNodeList [0x00001298:0x00001898]
                  │        │     └─ FileNodeListFragment [0x00001298:0x00001898] ID=3 Seq=0
                  │        │        ├─ [0x000012A8:0x000012C0] RevisionManifestStart6FND 0
                  │        │        ├─ [0x000012C0:0x000012E1] ObjectGroupListReferenceFND 2
                  │        │        │  └─ FileNodeList [0x00001448:0x00001A48]
                  │        │        │     └─ FileNodeListFragment [0x00001448:0x00001A48] ID=4 Seq=0
                  │        │        │        ├─ [0x00001458:0x00001470] ObjectGroupStartFND 0
                  │        │        │        └─ [0x00001470:0x00001474] ObjectGroupEndFND 0
                  │        │        └─ [0x000012E1:0x000012FA] ObjectInfoDependencyOverridesFND 1
                  └─ [0x0000042B:0x00000446] FileDataStoreListReferenceFND 2
                     └─ FileNodeList [0x00000BE8:0x00001178]
                        └─ FileNodeListFragment [0x00000BE8:0x00001178] ID=5 Seq=0
                           └─ [0x00000BF8:0x00000C20] FileDataStoreObjectReferenceFND 1
        """
        logger.debug("[DISPLAY] OneDocument tree:")
        if self.root_file_node_list is not None:
            self.root_file_node_list.display()

    def get_files(self):
        """OneNote 문서에 포함된 파일 데이터를 추출하여 딕셔너리로 반환한다.

        Returns:
            Dict[str, dict]: GUID를 키로 하며, 각 값은 다음 필드를 포함:
                - extension: 파일 확장자 (예: ".png", ".jpg")
                - content:   파일 바이너리 데이터
                - identity:  파일 데이터 객체의 OID 문자열 (ExtendedGUID)
                - filename:  원본 파일명. property set에서 매칭된 경우에만 할당되며,
                             매칭되지 않는 내부 변환 포맷(xps, emf 등)은 빈 문자열.

        파일 데이터는 두 종류의 FileNode에서 수집한다:
        - FileDataStoreObjectReferenceFND: 파일의 바이너리 content를 제공
        - ObjectDeclarationFileData3RefCountFND: 파일의 extension, identity를 제공

        filename은 property set에서 container OID와 identity를 매칭하여 할당한다.
        상세 매칭 규칙은 아래 주석 참조.
        """
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
                        self._files[str(node.data.guidReference)] = {"extension": "", "content": "", "identity": "", "filename": ""}
                    self._files[str(node.data.guidReference)]["content"] = node.data.fileDataStoreObject.FileData
                elif isinstance(node.data, ObjectDeclarationFileData3RefCountFND):
                    guid = node.data.FileDataReference.StringData.replace("<ifndf>{", "").replace("}", "")
                    guid = guid.lower()
                    if not guid in self._files:
                        self._files[guid] = {"extension": "", "content": "", "identity": "", "filename": ""}
                    self._files[guid]["extension"] = node.data.Extension.StringData
                    self._files[guid]["identity"] = str(node.data.oid)

        # EmbeddedFileName / ImageFilename을 properties에서 조회하여 files에 할당
        #
        # OneNote는 하나의 이미지를 여러 포맷으로 저장할 수 있다:
        #   jcidEmbeddedFileNode: EmbeddedFileContainer → 원본 파일 (EmbeddedFileName)
        #   jcidImageNode:        PictureContainer      → 내부 렌더링 포맷 (xps, emf 등)
        #   jcidImageNode:        WebPictureContainer14  → 웹 최적화 변환 (png 등)
        #
        # jcidImageNode에 WebPictureContainer14가 존재하면 원본은 별도의
        # jcidEmbeddedFileNode에서 관리되므로, PictureContainer에 ImageFilename을
        # 할당하지 않는다. WebPictureContainer14가 없는 경우에만 PictureContainer가
        # 직접 저장된 원본 이미지이므로 ImageFilename을 할당한다.
        for prop in self.get_properties():
            val = prop["val"]

            if prop["type"] == "jcidEmbeddedFileNode":
                container = val.get("EmbeddedFileContainer")
                filename = val.get("EmbeddedFileName")
                if container and filename:
                    identity_key = container[0]
                    for file_entry in self._files.values():
                        if file_entry["identity"] == identity_key:
                            file_entry["filename"] = filename
                            source_filepath = val.get('SourceFilepath')
                            if source_filepath:
                                file_entry["source_filepath"] = source_filepath
                            break

            elif prop["type"] == "jcidImageNode":
                # WebPictureContainer14가 있으면 내부 변환 포맷이므로 skip
                if val.get("WebPictureContainer14"):
                    continue
                container = val.get("PictureContainer")
                filename = val.get("ImageFilename")
                if container and filename:
                    identity_key = container[0]
                    for file_entry in self._files.values():
                        if file_entry["identity"] == identity_key:
                            file_entry["filename"] = filename
                            break

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

                filename = str(file_entry.get("filename", ""))
                source_filepath = str(file_entry.get("source_filepath", ""))

                key_str = str(key)
                if files_include_content:
                    file_info: Dict[str, str] = {
                        "extension": extension,
                        "content": content_bytes.hex(),
                        "identity": identity,
                    }
                else:
                    file_info = {
                        "extension": extension,
                        "identity": identity,
                        "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
                    }

                if filename:
                    file_info["filename"] = filename
                if source_filepath:
                    file_info["source_filepath"] = source_filepath

                files_json[key_str] = file_info

            res["files"] = files_json

        return res

    def __str__(self):
        return f'{str(self.header)}\n{str(self.rootFileNode)}'



