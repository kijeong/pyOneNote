from pyOneNote.Header import *
from pyOneNote.FileNode import *
from pyOneNote.OneDocument import *
import math
import sys
import os
import logging
import argparse
import json

log = logging.getLogger()

def check_valid(file):
    # OneNote 파일 시그니처 확인 (MS-ONESTORE 2.3.1 Header 섹션 참조)
    # 파일의 첫 16바이트는 guidFileType으로 파일 형식을 식별
    if file.read(16) in (
        # .one 파일 시그니처: {7B5C52E4-D88C-4DA7-AEB1-5378D02996D3} (little-endian)
        b"\xE4\x52\x5C\x7B\x8C\xD8\xA7\x4D\xAE\xB1\x53\x78\xD0\x29\x96\xD3",
        # .onetoc2 파일 시그니처: {43FF2FA1-EFD9-4C76-9EE2-10EA5722765F} (little-endian)
        b"\xA1\x2F\xFF\x43\xD9\xEF\x76\x4C\x9E\xE2\x10\xEA\x57\x22\x76\x5F",
    ):
        return True
    return False


def process_onenote_file(file, output_dir, extension, json_output):
    if not check_valid(file):
        log.error("please provide valid One file")
        exit()

    file.seek(0)
    document = OneDocment(file)
    data = document.get_json()
    if not json_output:
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
        for name, file in data['files'].items():
            print('{}{} ({}):'.format(indent, name, file['identity']))
            print('\t{}Extension: {}'.format(indent, file['extension']))
            if(file['identity'] in file_metadata):
                for property_name, property_val in file_metadata[file['identity']].items():
                    print('{}{}: {}'.format(indent+'\t', property_name, str(property_val)))
            print('{}'.format( get_hex_format(file['content'][:256], 16, indent+'\t')))

        if extension and not extension.startswith("."):
            extension = "." + extension

        counter = 0
        for file_guid, file in document.get_files().items():
            with open(
                    os.path.join(output_dir,
                                 "file_{}{}{}".format(counter, file["extension"], extension)), "wb"
            ) as output_file:
                output_file.write(file["content"])
            counter += 1

    return json.dumps(data)


def get_hex_format(hex_str, col, indent):
    res = ''
    chars = (col*2)
    for i in range(math.ceil( len(hex_str)/chars)):
        segment = hex_str[i*chars: (i+1)*chars]
        res += indent + ' '.join([segment[i:i+2] for i in range(0, len(segment), 2)]) +'\n'
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-f", "--file", action="store", help="File to analyze", required=True)
    p.add_argument("-o", "--output-dir", action="store", default="./", help="Path where store extracted files")
    p.add_argument("-e", "--extension", action="store", default="", help="Append this extension to extracted file(s)")
    p.add_argument("-j", "--json", action="store_true", default=False, help="Generate JSON output only, no dumps or prints")

    args = p.parse_args()

    if not os.path.exists(args.file):
        sys.exit("File: %s doesn't exist", args.file)

    with open(args.file, "rb") as file:
        process_onenote_file(file, args.output_dir, args.extension, args.json)
        

if __name__ == "__main__":
    main()


