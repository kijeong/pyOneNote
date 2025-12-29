import re
from typing import Any, Dict, List, Optional, Set, Tuple

from pyOneNote.Header import Header
from pyOneNote.FileNode import (
    FileNodeList,
    FileDataStoreObjectReferenceFND,
    ObjectDeclarationFileData3RefCountFND,
)

DEBUG = True

class OneDocument:
    def __init__(self, fh_onenote, debug=False):
        self.debug = debug
        self._files = None
        self._properties= None
        self._links: Optional[List[Dict[str, str]]] = None
        self._global_identification_table= {}
        self.cur_revision = None
        self.header = Header(fh_onenote, debug=debug)
        self.container = None
        self.root_file_node_list = FileNodeList(fh_onenote, self, self.header.fcrFileNodeListRoot, self)

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
                self._properties.append({'type': str(node.data.body.jcid), 'identity':str(node.data.body.oid), 'val':node.propertySet.body.get_properties()})

        return  self._properties

    @staticmethod
    def _extract_urls_from_text(text: str) -> List[str]:
        matches = re.findall(r"(?:https?://|mailto:|onenote:)[^\s<>\"']+", text, flags=re.IGNORECASE)
        urls: List[str] = []
        seen: Set[str] = set()
        for match in matches:
            url = match.rstrip(")].,;:!?\"'\u3001\u3002")
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    def get_links(self, include_text_urls: bool = True) -> List[Dict[str, str]]:
        if self._links is not None:
            return self._links

        self._links = []
        seen: Set[Tuple[str, str]] = set()

        for property_set in self.get_properties():
            type_name = str(property_set.get('type', ''))
            identity = str(property_set.get('identity', ''))
            props: Dict[str, Any] = property_set.get('val', {})

            wz_hyperlink_url = props.get('WzHyperlinkUrl')
            if wz_hyperlink_url and self.debug:
                print(f'Found WzHyperlinkUrl: {wz_hyperlink_url}')  # Debug print
            if isinstance(wz_hyperlink_url, str):
                url = wz_hyperlink_url.rstrip('\x00').strip()
                if url:
                    key = (identity, url)
                    if key not in seen:
                        seen.add(key)
                        self._links.append(
                            {
                                'type': type_name,
                                'identity': identity,
                                'url': url,
                                'source': 'WzHyperlinkUrl',
                            }
                        )

            if include_text_urls:
                rich_text = props.get('RichEditTextUnicode')
                if rich_text and self.debug:
                    print(f'Found RichEditTextUnicode: {rich_text}')  # Debug print
                if isinstance(rich_text, str):
                    for url in self._extract_urls_from_text(rich_text):
                        key = (identity, url)
                        if key not in seen:
                            seen.add(key)
                            self._links.append(
                                {
                                    'type': type_name,
                                    'identity': identity,
                                    'url': url,
                                    'source': 'RichEditTextUnicode',
                                }
                            )

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

    def get_json(self):
        files_in_hex = {}
        for key, file_entry in self.get_files().items():
            files_in_hex[key] = {'extension': file_entry['extension'],
                                 'content': file_entry['content'].hex(),
                                 'identity': file_entry['identity']}

        res = {
            "headers": self.header.convert_to_dictionary(),
            "properties": self.get_properties(),
            "links": self.get_links(),
            "files": files_in_hex,
        }

        return res

    def __str__(self):
        return '{}\n{}\n{}'.format(str(self.header),
                                   str(self.rootFileNode))



