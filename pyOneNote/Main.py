from pyOneNote.OneDocument import OneDocument, DEBUG
import math
import sys
import os
import logging
import argparse
import json
from typing import BinaryIO, Optional, Set, Union

log = logging.getLogger()


def check_valid(fh_onenote):
    # OneNote 파일 시그니처 확인 (MS-ONESTORE 2.3.1 Header 섹션 참조)
    # 파일의 첫 16바이트는 guidFileType으로 파일 형식을 식별
    if fh_onenote.read(16) in (
        # .one 파일 시그니처: {7B5C52E4-D88C-4DA7-AEB1-5378D02996D3} (little-endian)
        b"\xE4\x52\x5C\x7B\x8C\xD8\xA7\x4D\xAE\xB1\x53\x78\xD0\x29\x96\xD3",
        # .onetoc2 파일 시그니처: {43FF2FA1-EFD9-4C76-9EE2-10EA5722765F} (little-endian)
        b"\xA1\x2F\xFF\x43\xD9\xEF\x76\x4C\x9E\xE2\x10\xEA\x57\x22\x76\x5F",
    ):
        return True
    return False


def process_onenote_file(
    fh_onenote: BinaryIO,
    output_dir: str,
    extension: str,
    json_output: Union[bool, str],
    json_include_sections: Optional[Set[str]] = None,
    json_files_include_content: bool = True,
) -> None:
    if not check_valid(fh_onenote):
        log.error("please provide valid One file")
        exit()

    fh_onenote.seek(0)
    debug_mode = DEBUG
    if json_output:
        debug_mode = False

    document = OneDocument(fh_onenote, debug=debug_mode)
    if json_output:
        data = document.get_json(
            include_sections=json_include_sections,
            files_include_content=json_files_include_content,
        )
        json_payload = json.dumps(data, ensure_ascii=False, indent=2)
        if isinstance(json_output, str):
            with open(json_output, "w", encoding="utf-8") as json_fp:
                json_fp.write(json_payload)
        else:
            print(json_payload)
        return

    data = document.get_json()
    if output_dir:
        print('Headers\n####################################################################')
        indent = '\t'
        for key, header in data['headers'].items():
            print('{}{}: {}'.format(indent, key, header))

        print('\n\nProperties\n####################################################################')
        indent = '\t'
        file_metadata ={}
        for propertySet in data['properties']:
            print('{}{}({}):'.format(indent, propertySet['type'], propertySet['identity']))
            # jcidEmbeddedFileNode (0x00060035): 내장된 파일 노드 (MS-ONE 2.2.32)
            # 문서에 첨부된 파일 정보를 포함하는 노드 타입
            if propertySet['type'] == "jcidEmbeddedFileNode":
                if 'EmbeddedFileContainer' in propertySet['val']:
                    file_metadata[propertySet['val']['EmbeddedFileContainer'][0]] = propertySet['val']
            # jcidImageNode (0x00060011): 이미지 노드 (MS-ONE 2.2.24)
            # 문서에 포함된 이미지 정보를 포함하는 노드 타입
            if propertySet['type'] == "jcidImageNode":
                if 'PictureContainer' in propertySet['val']:
                    file_metadata[propertySet['val']['PictureContainer'][0]] = propertySet['val']


            for property_name, property_val in propertySet['val'].items():
                print('{}{}: {}'.format(indent+'\t', property_name, str(property_val)))
            print("")

        print('\n\nEmbedded Files\n####################################################################')
        indent = '\t'
        for name, embedded_file in data['files'].items():
            print('{}{} ({}):'.format(indent, name, embedded_file['identity']))
            print('\t{}Extension: {}'.format(indent, embedded_file['extension']))
            if(embedded_file['identity'] in file_metadata):
                for property_name, property_val in file_metadata[embedded_file['identity']].items():
                    print('{}{}: {}'.format(indent+'\t', property_name, str(property_val)))
            print('{}'.format( get_hex_format(embedded_file['content'][:256], 16, indent+'\t')))

        if extension and not extension.startswith("."):
            extension = "." + extension

        counter = 0
        for file_guid, extracted_file in document.get_files().items():
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)

            with open(
                    os.path.join(output_dir,
                                 "file_{}{}{}".format(counter, extracted_file["extension"], extension)), "wb"
            ) as output_file:
                output_file.write(extracted_file["content"])
            counter += 1

    return


def get_hex_format(hex_str, col, indent):
    res = ''
    chars = (col*2)
    for i in range(math.ceil( len(hex_str)/chars)):
        segment = hex_str[i*chars: (i+1)*chars]
        res += indent + ' '.join([segment[i:i+2] for i in range(0, len(segment), 2)]) +'\n'
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-f", "--input", action="store", help="File to analyze", required=True)
    p.add_argument("-o", "--output-dir", action="store", default="./", help="Path where store extracted files")
    p.add_argument("-e", "--extension", action="store", default="", help="Append this extension to extracted file(s)")
    p.add_argument("-j", "--json", nargs="?", const=True, default=False, metavar="JSON_PATH",
                   help="Generate JSON output only. Optionally write it to JSON_PATH instead of stdout.")
    p.add_argument(
        "--json-include",
        action="store",
        default=None,
        metavar="SECTIONS",
        help="Comma-separated list of top-level JSON sections to include: headers,properties,links,files",
    )
    p.add_argument(
        "--json-files-no-content",
        action="store_true",
        default=False,
        help="When 'files' is included in JSON output, omit file content and include content_sha256.",
    )

    args = p.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"File: {args.input} doesn't exist")

    if (args.json_include is not None or args.json_files_no_content) and not args.json:
        p.error("--json-include/--json-files-no-content requires --json")

    json_include_sections: Optional[Set[str]] = None
    if args.json_include is not None:
        json_include_sections = {s.strip().lower() for s in args.json_include.split(",") if s.strip()}
        if not json_include_sections:
            p.error("--json-include must contain at least one section")

        supported_sections = {"headers", "properties", "links", "files"}
        unknown_sections = json_include_sections - supported_sections
        if unknown_sections:
            supported_str = ", ".join(sorted(supported_sections))
            unknown_str = ", ".join(sorted(unknown_sections))
            p.error(f"Unsupported section name(s): {unknown_str}. Supported: {supported_str}")

    with open(args.input, "rb") as fp_onenote:
        process_onenote_file(
            fp_onenote,
            args.output_dir,
            args.extension,
            args.json,
            json_include_sections=json_include_sections,
            json_files_include_content=not args.json_files_no_content,
        )
        

if __name__ == "__main__":
    main()


