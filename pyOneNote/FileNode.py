import uuid
import struct
from datetime import datetime, timedelta
import locale

class FileNodeListHeader:
    """MS-ONESTORE 2.4.2 FileNodeListHeader 구조체
    FileNodeListFragment의 시작을 지정하는 헤더 구조체"""
    def __init__(self, fh_onenote):
        # uintMagic: 0xA4567AB1F5F7F4C4 (FileNodeList 식별자)
        # FileNodeListID: 파일 노드 리스트의 고유 식별자
        # nFragmentSequence: fragment의 순차 번호 (0부터 시작)
        self.uintMagic, self.FileNodeListID, self.nFragmentSequence = struct.unpack('<8sII', fh_onenote.read(16))


class FileNodeList:
    """MS-ONESTORE 2.4 File Node List
    파일 내 데이터를 저장하고 참조하기 위한 FileNode 구조체들의 리스트"""
    def __init__(self, fh_onenote, document, file_chunk_reference, container):
        fh_onenote.seek(file_chunk_reference.stp)
        self.end = file_chunk_reference.stp + file_chunk_reference.cb
        self.fragments = []
        self.container = container

        # FileNodeList는 하나 이상의 FileNodeListFragment로 구성됨
        # 각 fragment는 동일한 FileNodeListID를 가져야 함
        while True:
            section_end = file_chunk_reference.stp + file_chunk_reference.cb
            fragment = FileNodeListFragment(fh_onenote, document, section_end, self)
            self.fragments.append(fragment)
            if fragment.nextFragment.isFcrNil():
                break
            file_chunk_reference = fragment.nextFragment
            fh_onenote.seek(fragment.nextFragment.stp)


class FileNodeListFragment:
    """MS-ONESTORE 2.4.1 FileNodeListFragment 구조체
    FileNode 구조체들의 시퀀스를 포함하는 fragment"""
    def __init__(self, fh_onenote, document, end, file_node_list):
        self.fileNodes = []
        self.fileNodeListHeader = FileNodeListHeader(fh_onenote)
        self.container = file_node_list

        # FileNodeListFragment는 여러 개의 FileNode를 포함할 수 있음
        # ChunkTerminatorFND (0xFF) 또는 빈 노드(0x00)를 만나면 종료
        while fh_onenote.tell() + 24 < end:
            node = FileNode(fh_onenote, document, self)
            self.fileNodes.append(node)
            if node.file_node_header.file_node_id == 255 or node.file_node_header.file_node_id == 0:
                break

        fh_onenote.seek(end - 20)
        self.nextFragment = FileChunkReference64x32(fh_onenote.read(12))
        self.footer, = struct.unpack('<Q', fh_onenote.read(8))


class FileNodeHeader:
    """MS-ONESTORE 2.4.3 FileNode Header
    FileNode의 타입과 크기 정보를 포함하는 4바이트 헤더
    
    비트 필드 구조:
    - FileNodeID (0-9): 노드 타입 식별자
    - Size (10-22): FileNode 구조체의 크기(바이트)
    - StpFormat (23-24): 파일 포인터의 크기와 형식
    - CbFormat (25-26): 데이터 크기 필드의 형식
    - BaseType (27-30): FileNode의 기본 타입
    - Reserved (31): 예약 비트
    """
    # MS-ONESTORE의 FileNode.FileNodeID -> 노드 타입 이름 매핑
    # value 튜플 의미: (FileNodeID, expected_base_type, type_name)
    # - FileNodeID: 10비트 노드 타입 값
    # - expected_base_type: 스펙 상 해당 FileNode 타입에서 기대되는 BaseType 힌트(0/1/2)
    #   * 현재 파서 로직은 헤더의 BaseType 필드를 직접 사용하며, 이 값은 참고용으로만 유지됨
    # - type_name: MS-ONESTORE에 등장하는 구조체/파일 노드 타입 이름
    #
    # 스펙 대조 결과:
    # - MS-ONESTORE 2.5 "File Node Types"(2.5.1~2.5.33) 항목은 모두 포함됨
    # - 아래 항목들 중 일부는 2.5 목록 외이지만 문서에서 별도 섹션으로 정의되거나(예: 2.3.4.1 HashedChunkDescriptor2FND)
    #   시퀀스 종료/레거시 목적(예: ChunkTerminatorFND, RevisionManifestEndFND, ObjectGroupEndFND,
    #   GlobalIdTableStart2FND, GlobalIdTableEndFNDX)으로 등장함
    _FileNodeIDs = {
        # 2.5.1~2.5.8: Object Space / Revision Manifest
        0x004: (0x004, 0, "ObjectSpaceManifestRootFND"),
        0x008: (0x008, 2, "ObjectSpaceManifestListReferenceFND"),
        0x00C: (0x00C, 0, "ObjectSpaceManifestListStartFND"),
        0x010: (0x010, 2, "RevisionManifestListReferenceFND"),
        0x014: (0x014, 0, "RevisionManifestListStartFND"),
        0x01B: (0x01B, 0, "RevisionManifestStart4FND"),
        0x01C: (0x01C, 0, "RevisionManifestEndFND"),
        0x01E: (0x01E, 0, "RevisionManifestStart6FND"),
        0x01F: (0x01F, 0, "RevisionManifestStart7FND"),

        # 2.5.9~2.5.12(+부가): Global Identification Table
        0x021: (0x021, 0, "GlobalIdTableStartFNDX"),
        0x022: (0x022, 0, "GlobalIdTableStart2FND"),
        0x024: (0x024, 0, "GlobalIdTableEntryFNDX"),
        0x025: (0x025, 0, "GlobalIdTableEntry2FNDX"),
        0x026: (0x026, 0, "GlobalIdTableEntry3FNDX"),
        0x028: (0x028, 0, "GlobalIdTableEndFNDX"),

        # 2.5.23~2.5.26: Object Declaration
        0x02D: (0x02D, 1, "ObjectDeclarationWithRefCountFNDX"),
        0x02E: (0x02E, 1, "ObjectDeclarationWithRefCount2FNDX"),

        # 2.5.13~2.5.14: Object Revision
        0x041: (0x041, 1, "ObjectRevisionWithRefCountFNDX"),
        0x042: (0x042, 1, "ObjectRevisionWithRefCount2FNDX"),

        # 2.5.15~2.5.16: Root Object References
        0x059: (0x059, 0, "RootObjectReference2FNDX"),
        0x05A: (0x05A, 0, "RootObjectReference3FND"),

        # 2.5.17~2.5.18: Revision Role
        0x05C: (0x05C, 0, "RevisionRoleDeclarationFND"),
        0x05D: (0x05D, 0, "RevisionRoleAndContextDeclarationFND"),

        # 2.5.27~2.5.28: File Data (embedded files)
        0x072: (0x072, 0, "ObjectDeclarationFileData3RefCountFND"),
        0x073: (0x073, 0, "ObjectDeclarationFileData3LargeRefCountFND"),

        # 2.5.19~2.5.20: Encryption / Dependency Overrides
        0x07C: (0x07C, 1, "ObjectDataEncryptionKeyV2FNDX"),
        0x084: (0x084, 1, "ObjectInfoDependencyOverridesFND"),

        # 2.5.33: Signature
        0x08C: (0x08C, 0, "DataSignatureGroupDefinitionFND"),

        # 2.5.21~2.5.22: File Data Store
        0x090: (0x090, 2, "FileDataStoreListReferenceFND"),
        0x094: (0x094, 1, "FileDataStoreObjectReferenceFND"),

        # 2.5.25~2.5.30: Object Declaration (v2, read-only)
        0x0A4: (0x0A4, 1, "ObjectDeclaration2RefCountFND"),
        0x0A5: (0x0A5, 1, "ObjectDeclaration2LargeRefCountFND"),

        # 2.5.31~2.5.32(+부가): Object Group
        0x0B0: (0x0B0, 2, "ObjectGroupListReferenceFND"),
        0x0B4: (0x0B4, 0, "ObjectGroupStartFND"),
        0x0B8: (0x0B8, 0, "ObjectGroupEndFND"),

        # 2.3.4.1: Hashed Chunk List
        0x0C2: (0x0C2, 1, "HashedChunkDescriptor2FND"),

        # 2.5.29~2.5.30: ReadOnlyObjectDeclaration2*
        0x0C4: (0x0C4, 1, "ReadOnlyObjectDeclaration2RefCountFND"),
        0x0C5: (0x0C5, 1, "ReadOnlyObjectDeclaration2LargeRefCountFND"),

        # FileNodeListFragment 내 종료 마커
        0x0FF: (0x0FF, -1, "ChunkTerminatorFND")
    }

    def __init__(self, fh_onenote):
        fileNodeHeader, = struct.unpack('<I', fh_onenote.read(4))
        # FileNodeID: 노드 타입을 나타내는 10비트 값
        self.file_node_id = fileNodeHeader & 0x3ff
        entry = self._FileNodeIDs.get(self.file_node_id)
        if not entry:
            self.file_node_type = "UnknownType_0x{:03X}".format(self.file_node_id)
        else:
             self.file_node_type = entry[2]

        # Size: FileNode 구조체의 전체 크기 (13비트)
        self.size = (fileNodeHeader >> 10) & 0x1fff
        # StpFormat: 파일 포인터 형식 (0=8바이트, 1=4바이트, 2=2바이트 압축, 3=4바이트 압축)
        self.stpFormat = (fileNodeHeader >> 23) & 0x3
        # CbFormat: 데이터 크기 필드 형식 (0=4바이트, 1=8바이트, 2=1바이트 압축, 3=2바이트 압축)
        self.cbFormat = (fileNodeHeader >> 25) & 0x3
        # BaseType: 0=데이터 없음, 1=데이터 참조, 2=FileNodeList 참조
        self.baseType = (fileNodeHeader >> 27) & 0xf
        self.reserved = (fileNodeHeader >> 31)

def get_containers_name_upwards(container):
    names = []
    cur_container = container
    while cur_container:
        names.append(type(cur_container).__name__)
        cur_container = cur_container.container
    names.reverse()
    return '/'.join([str(name) for name in names])

class FileNode:
    count = 0
    def __init__(self, fh_onenote, document, file_node_list):
        self.document= document
        self.file_node_header = FileNodeHeader(fh_onenote)
        self.container = file_node_list
 
        if self.document.debug:
            print(f"{get_containers_name_upwards(self.container)} {fh_onenote.tell()} {self.file_node_header.file_node_type} {self.file_node_header.baseType}")
        self.children = []
        FileNode.count += 1
        if self.file_node_header.file_node_type == "ObjectGroupStartFND":
            self.data = ObjectGroupStartFND(fh_onenote)
        elif self.file_node_header.file_node_type == "ObjectSpaceManifestListReferenceFND":
            self.data = ObjectSpaceManifestListReferenceFND(fh_onenote, self.file_node_header)
        elif self.file_node_header.file_node_type == "ObjectSpaceManifestListStartFND":
            self.data = ObjectSpaceManifestListStartFND(fh_onenote)
        elif self.file_node_header.file_node_type == "RevisionManifestListReferenceFND":
            self.data = RevisionManifestListReferenceFND(fh_onenote, self.file_node_header)
        elif self.file_node_header.file_node_type == "RevisionManifestListStartFND":
            self.data = RevisionManifestListStartFND(fh_onenote)
        elif self.file_node_header.file_node_type == "RevisionManifestStart4FND":
            self.data = RevisionManifestStart4FND(fh_onenote)
            self.document.cur_revision = self.data.rid
        elif self.file_node_header.file_node_type == "RevisionManifestStart6FND":
            self.data = RevisionManifestStart6FND(fh_onenote)
            self.document.cur_revision = self.data.rid
        elif self.file_node_header.file_node_type == "ObjectGroupListReferenceFND":
            self.data = ObjectGroupListReferenceFND(fh_onenote, self.file_node_header)
        elif self.file_node_header.file_node_type == "GlobalIdTableEntryFNDX":
            self.data = GlobalIdTableEntryFNDX(fh_onenote)
            if not self.document.cur_revision in self.document._global_identification_table:
                self.document._global_identification_table[self.document.cur_revision] = {}

            self.document._global_identification_table[self.document.cur_revision][self.data.index] = self.data.guid
        elif self.file_node_header.file_node_type == "DataSignatureGroupDefinitionFND":
            self.data = DataSignatureGroupDefinitionFND(fh_onenote)
        elif self.file_node_header.file_node_type == "ObjectDeclaration2RefCountFND":
            self.data = ObjectDeclaration2RefCountFND(fh_onenote, self.document, self.file_node_header)
            current_offset = fh_onenote.tell()
            if self.data.body.jcid.IsPropertySet:
                fh_onenote.seek(self.data.ref.stp)
                self.propertySet = ObjectSpaceObjectPropSet(fh_onenote, document)
            fh_onenote.seek(current_offset)
        elif self.file_node_header.file_node_type == "ReadOnlyObjectDeclaration2LargeRefCountFND":
            self.data = ReadOnlyObjectDeclaration2LargeRefCountFND(fh_onenote, self.document, self.file_node_header)
        elif self.file_node_header.file_node_type == "ReadOnlyObjectDeclaration2RefCountFND":
            self.data = ReadOnlyObjectDeclaration2RefCountFND(fh_onenote, self.document, self.file_node_header)
        elif self.file_node_header.file_node_type == "FileDataStoreListReferenceFND":
            self.data = FileDataStoreListReferenceFND(fh_onenote, self.file_node_header)
        elif self.file_node_header.file_node_type == "FileDataStoreObjectReferenceFND":
            self.data = FileDataStoreObjectReferenceFND(fh_onenote, self.file_node_header)
        elif self.file_node_header.file_node_type == "ObjectDeclaration2Body":
            self.data = ObjectDeclaration2Body(fh_onenote, self.document)
        elif self.file_node_header.file_node_type == "ObjectInfoDependencyOverridesFND":
            self.data = ObjectInfoDependencyOverridesFND(fh_onenote, self.file_node_header, self.document)
        elif self.file_node_header.file_node_type == "RootObjectReference2FNDX":
            self.data = RootObjectReference2FNDX(fh_onenote, self.document)
        elif self.file_node_header.file_node_type == "RootObjectReference3FND":
            self.data = RootObjectReference3FND(fh_onenote)
        elif self.file_node_header.file_node_type == "ObjectSpaceManifestRootFND":
            self.data = ObjectSpaceManifestRootFND(fh_onenote)
        elif self.file_node_header.file_node_type == "ObjectDeclarationFileData3RefCountFND":
            self.data = ObjectDeclarationFileData3RefCountFND(fh_onenote, self.document)
        elif self.file_node_header.file_node_type == "RevisionRoleDeclarationFND":
            self.data = RevisionRoleDeclarationFND(fh_onenote)
        elif self.file_node_header.file_node_type == "RevisionRoleAndContextDeclarationFND":
            self.data = RevisionRoleAndContextDeclarationFND(fh_onenote)
        elif self.file_node_header.file_node_type == "RevisionManifestStart7FND":
            self.data = RevisionManifestStart7FND(fh_onenote)
            self.document.cur_revision = self.data.base.rid
        elif self.file_node_header.file_node_type in ["RevisionManifestEndFND", "ObjectGroupEndFND"]:
            # no data part
            self.data = None
        else:
            p = 1

        current_offset = fh_onenote.tell()
        if self.file_node_header.baseType == 2:
            self.children.append(FileNodeList(fh_onenote, self.document, self.data.ref, self))
        fh_onenote.seek(current_offset)


class ExtendedGUID:
    """MS-ONESTORE 2.2.1 ExtendedGUID 구조체
    GUID와 버전 번호를 포함하는 20바이트 구조체
    Global Identification Table에서 GUID를 참조할 때 사용"""
    def __init__(self, fh_onenote):
        # guid: 16바이트 GUID (little-endian)
        # n: 버전/시퀀스 번호 (4바이트)
        self.guid, self.n = struct.unpack('<16sI', fh_onenote.read(20))
        self.guid = uuid.UUID(bytes_le=self.guid)

    def __repr__(self):
        return 'ExtendedGUID:(guid:{}, n:{})'.format(self.guid, self.n)


class FileNodeChunkReference:
    """MS-ONESTORE 2.2.4.2 FileNodeChunkReference 구조체
    FileNode가 참조하는 데이터의 파일 내 위치와 크기를 지정
    
    StpFormat과 CbFormat에 따라 크기가 결정됨:
    - StpFormat: 파일 포인터 형식 (0=8바이트, 1=4바이트, 2=2바이트 압축, 3=4바이트 압축)
    - CbFormat: 데이터 크기 형식 (0=4바이트, 1=8바이트, 2=1바이트 압축, 3=2바이트 압축)
    """
    def __init__(self, fh_onenote, stpFormat, cbFormat):
        data_size = 0
        stp_compressed = False
        stp_type = ''
        if stpFormat == 0:
            stp_type = 'Q'
            data_size += 8
            self.invalid = 0xffffffffffffffff
        elif stpFormat == 1:
            stp_type = 'I'
            data_size += 4
            self.invalid = 0xffffffff
        elif stpFormat == 2:
            stp_type = 'H'
            data_size += 2
            stp_compressed = True
            self.invalid = 0x7fff8
        elif stpFormat == 3:
            stp_type = 'I'
            data_size += 4
            stp_compressed = True
            self.invalid = 0x7fffffff8

        cb_type = ''
        cb_compressed = False
        if cbFormat == 0:
            cb_type = 'I'
            data_size += 4
        elif cbFormat == 1:
            cb_type = 'Q'
            data_size += 8
        elif cbFormat == 2:
            cb_type = 'B'
            data_size += 1
            cb_compressed = True
        elif cbFormat == 3:
            cb_type = 'H'
            data_size += 2
            cb_compressed = True

        self.stp, self.cb = struct.unpack('<{}{}'.format(stp_type, cb_type), fh_onenote.read(data_size))
        if stp_compressed:
            self.stp *= 8

        if cb_compressed:
            self.cb *= 8

    def isFcrNil(self):
        res = False
        res = (self.stp & self.invalid) == self.invalid and self.cb == 0
        return res

    def __repr__(self):
        return 'FileChunkReference:(stp:{}, cb:{})'.format(self.stp, self.cb)


class FileChunkReference64x32(FileNodeChunkReference):
    """MS-ONESTORE 2.2.4.4 FileChunkReference64x32 구조체
    stp 필드가 8바이트, cb 필드가 4바이트인 12바이트 파일 참조 구조체
    주로 헤더에서 FileNodeList 위치를 참조할 때 사용"""
    def __init__(self, raw_bytes: bytes):
        # stp: 파일 내 데이터 위치 (8바이트)
        # cb: 참조 데이터의 크기 (4바이트)
        self.stp, self.cb = struct.unpack('<QI', raw_bytes)
        self.invalid = 0xffffffffffffffff

    def __repr__(self):
        return 'FileChunkReference64x32:(stp:{}, cb:{})'.format(self.stp, self.cb)


class FileChunkReference32(FileNodeChunkReference):
    """MS-ONESTORE 2.2.4.1 FileChunkReference32 구조체
    stp와 cb 필드가 각각 4바이트인 8바이트 파일 참조 구조체"""
    def __init__(self, raw_bytes: bytes):
        # stp: 파일 내 데이터 위치 (4바이트)
        # cb: 참조 데이터의 크기 (4바이트)
        self.stp, self.cb = struct.unpack('<II', raw_bytes)
        self.invalid = 0xffffffff

    def __repr__(self):
        return 'FileChunkReference32:(stp:{}, cb:{})'.format(self.stp, self.cb)


class ObjectGroupStartFND:
    def __init__(self, fh_onenote):
        self.oid = ExtendedGUID(fh_onenote)


class ObjectSpaceManifestRootFND:
    def __init__(self, fh_onenote):
        self.gosidRoot = ExtendedGUID(fh_onenote)


class ObjectSpaceManifestListStartFND:
    def __init__(self, fh_onenote):
        self.gosid = ExtendedGUID(fh_onenote)


class ObjectSpaceManifestListReferenceFND:
    def __init__(self, fh_onenote, file_node_header):
        self.ref = FileNodeChunkReference(fh_onenote, file_node_header.stpFormat, file_node_header.cbFormat)
        self.gosid = ExtendedGUID(fh_onenote)


class RevisionManifestListReferenceFND:
    def __init__(self, fh_onenote, file_node_header):
        self.ref = FileNodeChunkReference(fh_onenote, file_node_header.stpFormat, file_node_header.cbFormat)


class RevisionManifestListStartFND:
    def __init__(self, fh_onenote):
        self.gosid = ExtendedGUID(fh_onenote)
        self.nInstance = fh_onenote.read(4)


class RevisionManifestStart4FND:
    def __init__(self, fh_onenote):
        self.rid = ExtendedGUID(fh_onenote)
        self.ridDependent = ExtendedGUID(fh_onenote)
        self.timeCreation, self.RevisionRole, self.odcsDefault = struct.unpack('<8sIH', fh_onenote.read(14))


class RevisionManifestStart6FND:
    def __init__(self, fh_onenote):
        self.rid = ExtendedGUID(fh_onenote)
        self.ridDependent = ExtendedGUID(fh_onenote)
        self.RevisionRole, self.odcsDefault = struct.unpack('<IH', fh_onenote.read(6))


class ObjectGroupListReferenceFND:
    def __init__(self, fh_onenote, file_node_header):
        self.ref = FileNodeChunkReference(fh_onenote, file_node_header.stpFormat, file_node_header.cbFormat)
        self.ObjectGroupID = ExtendedGUID(fh_onenote)


class GlobalIdTableEntryFNDX:
    def __init__(self, fh_onenote):
        self.index, self.guid = struct.unpack('<I16s', fh_onenote.read(20))
        self.guid = uuid.UUID(bytes_le=self.guid)


class DataSignatureGroupDefinitionFND:
    def __init__(self, fh_onenote):
        self.DataSignatureGroup = ExtendedGUID(fh_onenote)


class ObjectDeclaration2LargeRefCountFND:
    def __init__(self, fh_onenote, document, file_node_header):
        self.ref = FileNodeChunkReference(fh_onenote, file_node_header.stpFormat, file_node_header.cbFormat)
        self.body = ObjectDeclaration2Body(fh_onenote, document)
        self.cRef, = struct.unpack('<I', fh_onenote.read(4))


class ObjectDeclaration2RefCountFND:
    def __init__(self, fh_onenote, document, file_node_header):
        self.ref = FileNodeChunkReference(fh_onenote, file_node_header.stpFormat, file_node_header.cbFormat)
        self.body = ObjectDeclaration2Body(fh_onenote, document)
        self.cRef, = struct.unpack('<B', fh_onenote.read(1))


class ReadOnlyObjectDeclaration2LargeRefCountFND:
    def __init__(self, fh_onenote, document, file_node_header):
        self.base = ObjectDeclaration2LargeRefCountFND(fh_onenote, document, file_node_header)
        self.md5Hash, = struct.unpack('16s', fh_onenote.read(16))


class ReadOnlyObjectDeclaration2RefCountFND:
    def __init__(self, fh_onenote, document, file_node_header):
        self.base = ObjectDeclaration2RefCountFND(fh_onenote, document, file_node_header)
        self.md5Hash, = struct.unpack('16s', fh_onenote.read(16))


class ObjectDeclaration2Body:
    def __init__(self, fh_onenote, document):
        self.oid = CompactID(fh_onenote, document)
        self.jcid = JCID(fh_onenote)
        data, = struct.unpack('B', fh_onenote.read(1))
        self.fHasOidReferences = (data & 0x1) != 0
        self.fHasOsidReferences = (data & 0x2) != 0


class ObjectInfoDependencyOverridesFND:
    def __init__(self, fh_onenote, file_node_header, document):
        self.ref = FileNodeChunkReference(fh_onenote, file_node_header.stpFormat, file_node_header.cbFormat)
        if self.ref.isFcrNil():
            data = ObjectInfoDependencyOverrideData(fh_onenote, document)


class FileDataStoreListReferenceFND:
    def __init__(self, fh_onenote, file_node_header):
        self.ref = FileNodeChunkReference(fh_onenote, file_node_header.stpFormat, file_node_header.cbFormat)


class FileDataStoreObjectReferenceFND:
    def __init__(self, fh_onenote, file_node_header):
        self.ref = FileNodeChunkReference(fh_onenote, file_node_header.stpFormat, file_node_header.cbFormat)
        self.guidReference, = struct.unpack('<16s', fh_onenote.read(16))
        self.guidReference = uuid.UUID(bytes_le=self.guidReference)
        current_offset = fh_onenote.tell()
        fh_onenote.seek(self.ref.stp)
        self.fileDataStoreObject = FileDataStoreObject(fh_onenote, self.ref)
        fh_onenote.seek(current_offset)

    def __str__(self):
        return 'FileDataStoreObjectReferenceFND: (guidReference:{},fileDataStoreObject:{}'.format(
            self.guidReference,
            str(self.fileDataStoreObject)
        )


class ObjectInfoDependencyOverrideData:
    def __init__(self, fh_onenote, document):
        self.c8BitOverrides, self.c32BitOverrides, self.crc = struct.unpack('<III', fh_onenote.read(12))
        self.Overrides1 = []
        for i in range(self.c8BitOverrides):
            self.Overrides1.append(ObjectInfoDependencyOverride8(fh_onenote, document))
        for i in range(self.c32BitOverrides):
            self.Overrides1.append(ObjectInfoDependencyOverride32(fh_onenote, document))


class ObjectInfoDependencyOverride8:
    def __init__(self, fh_onenote, document):
        self.oid = CompactID(fh_onenote, document)
        self.cRef, = struct.unpack('B', fh_onenote.read(1))


class ObjectInfoDependencyOverride32:
    def __init__(self, fh_onenote, document):
        self.oid = CompactID(fh_onenote, document)
        self.cRef, = struct.unpack('<I', fh_onenote.read(4))


class RootObjectReference2FNDX:
    def __init__(self, fh_onenote, document):
        self.oidRoot = CompactID(fh_onenote, document)
        self.RootRole, = struct.unpack('<I', fh_onenote.read(4))


class RootObjectReference3FND:
    def __init__(self, fh_onenote):
        self.oidRoot = ExtendedGUID(fh_onenote)
        self.RootRole, = struct.unpack('<I', fh_onenote.read(4))


class ObjectDeclarationFileData3RefCountFND:
    def __init__(self, fh_onenote, document):
        self.oid = CompactID(fh_onenote, document)
        self.jcid = JCID(fh_onenote)
        self.cRef, = struct.unpack('<B', fh_onenote.read(1))
        self.FileDataReference = StringInStorageBuffer(fh_onenote)
        self.Extension = StringInStorageBuffer(fh_onenote)

    def __str__(self):
        return 'ObjectDeclarationFileData3RefCountFND: (jcid:{}, Extension:{}, FileDataReference:{}'.format(
            self.jcid,
            self.Extension,
            self.FileDataReference
        )


class RevisionRoleDeclarationFND:
    def __init__(self, fh_onenote):
        self.rid = ExtendedGUID(fh_onenote)
        self.RevisionRole, = struct.unpack('<I', fh_onenote.read(4))


class RevisionRoleAndContextDeclarationFND:
    def __init__(self, fh_onenote):
        self.base = RevisionRoleDeclarationFND(fh_onenote)
        self.gctxid = ExtendedGUID(fh_onenote)


class RevisionManifestStart7FND:
    def __init__(self, fh_onenote):
        self.base = RevisionManifestStart6FND(fh_onenote)
        self.gctxid = ExtendedGUID(fh_onenote)


class CompactID:
    """MS-ONESTORE 2.2.2 CompactID 구조체
    ExtendedGUID를 압축하여 표현하는 4바이트 구조체
    Global Identification Table에서 GUID를 검색하여 전체 ExtendedGUID를 복원"""
    def __init__(self, fh_onenote, document):
        data, = struct.unpack('<I', fh_onenote.read(4))
        # n: ExtendedGUID.n 값 (8비트, 0-255)
        self.n = data & 0xff
        # guidIndex: Global ID Table에서의 GUID 인덱스 (24비트)
        self.guidIndex = data >> 8
        self.document = document
        self.current_revision = self.document.cur_revision

    def __str__(self):
        return '<ExtendedGUID> ({}, {})'.format(
        self.document._global_identification_table[self.current_revision][self.guidIndex],
        self.n)

    def __repr__(self):
        return '<ExtendedGUID> ({}, {})'.format(
        self.document._global_identification_table[self.current_revision][self.guidIndex],
        self.n)


class JCID:
    """MS-ONE/MS-ONESTORE JCID (JavaScript-like Compact Identifier)
    객체의 타입을 식별하는 4바이트 구조체
    
    비트 필드:
    - Index (0-15): JCID 인덱스
    - IsBinary (16): 바이너리 데이터 여부
    - IsPropertySet (17): PropertySet 여부
    - IsGraphNode (18): 그래프 노드 여부
    - IsFileData (19): 파일 데이터 객체 여부
    - IsReadOnly (20): 읽기 전용 여부
    """

    # 2.1.13 Property Set
    _jcid_name_mapping= {
        0x00120001: "jcidReadOnlyPersistablePropertyContainerForAuthor",
        0x00020001: "jcidPersistablePropertyContainerForTOC",
        0x00020001: "jcidPersistablePropertyContainerForTOCSection",
        0x00060007: "jcidSectionNode",
        0x00060008: "jcidPageSeriesNode",
        0x0006000B: "jcidPageNode",
        0x0006000C: "jcidOutlineNode",
        0x0006000D: "jcidOutlineElementNode",
        0x0006000E: "jcidRichTextOENode",
        0x00060011: "jcidImageNode",
        0x00060012: "jcidNumberListNode",
        0x00060019: "jcidOutlineGroup",
        0x00060022: "jcidTableNode",
        0x00060023: "jcidTableRowNode",
        0x00060024: "jcidTableCellNode",
        0x0006002C: "jcidTitleNode",
        0x00020030: "jcidPageMetaData",
        0x00020031: "jcidSectionMetaData",
        0x00060035: "jcidEmbeddedFileNode",
        0x00060037: "jcidPageManifestNode",
        0x00020038: "jcidConflictPageMetaData",
        0x0006003C: "jcidVersionHistoryContent",
        0x0006003D: "jcidVersionProxy",
        0x00120043: "jcidNoteTagSharedDefinitionContainer",
        0x00020044: "jcidRevisionMetaData",
        0x00020046: "jcidVersionHistoryMetaData",
        0x0012004D: "jcidParagraphStyleObject",
        0x0012004D: "jcidParagraphStyleObjectForText"
    }

    def __init__(self, fh_onenote):
        self.jcid, = struct.unpack('<I', fh_onenote.read(4))
        # index: JCID 타입 인덱스 (16비트)
        self.index = self.jcid & 0xffff
        # IsBinary: 바이너리 데이터를 포함하는지 여부
        self.IsBinary = ((self.jcid >> 16) & 0x1) == 1
        # IsPropertySet: PropertySet 구조체인지 여부
        self.IsPropertySet = ((self.jcid >> 17) & 0x1) == 1
        # IsGraphNode: 그래프 노드인지 여부
        self.IsGraphNode = ((self.jcid >> 18) & 0x1) == 1
        # IsFileData: 파일 데이터 객체인지 여부
        self.IsFileData = ((self.jcid >> 19) & 0x1) == 1
        # IsReadOnly: 읽기 전용인지 여부
        self.IsReadOnly = ((self.jcid >> 20) & 0x1) == 1

    def get_jcid_name(self):
        return self._jcid_name_mapping[self.jcid] if self.jcid in self._jcid_name_mapping else 'Unknown'

    def __str__(self):
        return self.get_jcid_name()

    def __repr__(self):
        return self.get_jcid_name()


class StringInStorageBuffer:
    """MS-ONESTORE 2.2.3 StringInStorageBuffer 구조체
    UTF-16으로 인코딩된 문자열을 저장하는 구조체"""
    def __init__(self, fh_onenote):
        # cch: 문자 개수 (UTF-16 문자 단위)
        self.cch, = struct.unpack('<I', fh_onenote.read(4))
        self.length_in_bytes = self.cch * 2
        # StringData: UTF-16LE로 인코딩된 문자열 데이터
        self.StringData, = struct.unpack('{}s'.format(self.length_in_bytes), fh_onenote.read(self.length_in_bytes))
        self.StringData = self.StringData.decode('utf-16')

    def __str__(self):
        return self.StringData


class FileDataStoreObject:
    """MS-ONESTORE 2.5.21 FileDataStoreObject 구조체
    파일 데이터를 저장하는 객체 (헤더, 데이터, 푸터로 구성)
    주로 내장된 파일이나 이미지 데이터를 저장할 때 사용"""
    def __init__(self, fh_onenote, fileNodeChunkReference):
        # guidHeader: 헤더 GUID (16바이트)
        # cbLength: 파일 데이터의 크기 (8바이트)
        # unused: 사용하지 않음 (4바이트, 0이어야 함)
        # reserved: 예약 (8바이트)
        self.guidHeader, self.cbLength, self.unused, self.reserved = struct.unpack('<16sQ4s8s', fh_onenote.read(36))
        # FileData: 실제 파일 데이터
        self.FileData, = struct.unpack('{}s'.format(self.cbLength), fh_onenote.read(self.cbLength))
        fh_onenote.seek(fileNodeChunkReference.stp + fileNodeChunkReference.cb - 16)
        # guidFooter: 푸터 GUID (guidHeader와 동일해야 함)
        self.guidFooter, = struct.unpack('16s', fh_onenote.read(16))
        self.guidHeader = uuid.UUID(bytes_le=self.guidHeader)
        self.guidFooter = uuid.UUID(bytes_le=self.guidFooter)

    def __str__(self):
        return self.FileData[:128].hex()


class ObjectSpaceObjectPropSet:
    """MS-ONESTORE 2.1.5 ObjectSpaceObjectPropSet 구조체
    객체의 속성 세트를 정의하는 구조체
    
    구성:
    - OIDs: ObjectID 스트림 (필수)
    - OSIDs: ObjectSpaceID 스트림 (선택적)
    - ContextIDs: Context ID 스트림 (선택적)
    - PropertySet: 실제 속성 데이터
    """
    def __init__(self, fh_onenote, document):
        # OIDs: 객체 ID 스트림 (필수)
        self.OIDs = ObjectSpaceObjectStreamOfIDs(fh_onenote, document)
        self.OSIDs = None
        # OSIDs: 객체 공간 ID 스트림 (OsidStreamNotPresent가 false일 때만)
        if not self.OIDs.header.OsidStreamNotPresent:
            self.OSIDs = ObjectSpaceObjectStreamOfIDs(fh_onenote, document)
        self.ContextIDs = None
        # ContextIDs: 확장 컨텍스트 ID 스트림 (ExtendedStreamsPresent가 true일 때만)
        if self.OIDs.header.ExtendedStreamsPresent:
            self.ContextIDs = ObjectSpaceObjectStreamOfIDs(fh_onenote, document)
        self.body = PropertySet(fh_onenote, self.OIDs, self.OSIDs, self.ContextIDs, document)


class ObjectSpaceObjectStreamOfIDs:
    def __init__(self, fh_onenote, document):
        self.header = ObjectSpaceObjectStreamHeader(fh_onenote)
        self.body = []
        self.head = 0
        for i in range(self.header.Count):
            self.body.append(CompactID(fh_onenote, document))

    def read(self):
        res = None
        if self.head < len(self.body):
            res = self.body[self.head]
        return res

    def reset(self):
        self.head = 0


class ObjectSpaceObjectStreamHeader:
    def __init__(self, fh_onenote):
        data, = struct.unpack('<I', fh_onenote.read(4))
        self.Count = data & 0xffffff
        self.ExtendedStreamsPresent = (data >> 30) & 1 == 1
        self.OsidStreamNotPresent = (data >> 31) & 1 == 1


class PropertySet:
    def __init__(self, fh_onenote, OIDs, OSIDs, ContextIDs, document):
        self.current = fh_onenote.tell()
        self.cProperties, = struct.unpack('<H', fh_onenote.read(2))
        self.rgPrids = []
        self.indent = ''
        self.document = document
        self.current_revision = document.cur_revision
        self._formated_properties = None
        for i in range(self.cProperties):
            self.rgPrids.append(PropertyID(fh_onenote))

        self.rgData = []
        for i in range(self.cProperties):
            prop_type = self.rgPrids[i].type
            if prop_type == 0x1:
                self.rgData.append(None)
            elif prop_type == 0x2:
                self.rgData.append(self.rgPrids[i].boolValue)
            elif prop_type == 0x3:
                self.rgData.append(struct.unpack('c', fh_onenote.read(1))[0])
            elif prop_type == 0x4:
                self.rgData.append(struct.unpack('2s', fh_onenote.read(2))[0])
            elif prop_type == 0x5:
                self.rgData.append(struct.unpack('4s', fh_onenote.read(4))[0])
            elif prop_type == 0x6:
                self.rgData.append(struct.unpack('8s', fh_onenote.read(8))[0])
            elif prop_type == 0x7:
                self.rgData.append(PrtFourBytesOfLengthFollowedByData(fh_onenote, self))
            elif prop_type == 0x8 or prop_type == 0x09:
                count = 1
                if prop_type == 0x09:
                    count, = struct.unpack('<I', fh_onenote.read(4))
                self.rgData.append(self.get_compact_ids(OIDs, count))
            elif prop_type == 0xA or prop_type == 0x0B:
                count = 1
                if prop_type == 0x0B:
                    count, = struct.unpack('<I', fh_onenote.read(4))
                self.rgData.append(self.get_compact_ids(OSIDs, count))
            elif prop_type == 0xC or prop_type == 0x0D:
                count = 1
                if prop_type == 0x0D:
                    count, = struct.unpack('<I', fh_onenote.read(4))
                self.rgData.append(self.get_compact_ids(ContextIDs, count))
            elif prop_type == 0x10:
                raise NotImplementedError('ArrayOfPropertyValues is not implement')
            elif prop_type == 0x11:
                self.rgData.append(PropertySet(fh_onenote, OIDs, OSIDs, ContextIDs, document))
            else:
                raise ValueError('rgPrids[i].type is not valid')

    @staticmethod
    def get_compact_ids(stream_of_context_ids, count):
        data = []
        for i in range(count):
            data.append(stream_of_context_ids.read())
        return data


    def get_properties(self):
        if self._formated_properties is not None :
            return self._formated_properties

        self._formated_properties = {}
        for i in range(self.cProperties):
            propertyName = str(self.rgPrids[i])
            if propertyName != 'Unknown':
                propertyVal = ''
                if isinstance(self.rgData[i], PrtFourBytesOfLengthFollowedByData):
                    if 'guid' in propertyName.lower():
                        propertyVal = uuid.UUID(bytes_le=self.rgData[i].Data).hex
                    else:
                        try:
                            propertyVal = self.rgData[i].Data.decode('utf-16')
                        except:
                            propertyVal = self.rgData[i].Data.hex()
                else:
                    property_name_lower =  propertyName.lower()
                    if 'time' in property_name_lower:
                        if len(self.rgData[i]) == 8:
                            timestamp_in_nano, = struct.unpack('<Q', self.rgData[i])
                            propertyVal = str(PropertySet.parse_filetime(timestamp_in_nano))
                        else:
                            timestamp_in_sec, = struct.unpack('<I', self.rgData[i])
                            propertyVal = str(PropertySet.time32_to_datetime(timestamp_in_sec))
                    elif 'height' in property_name_lower or \
                            'width' in property_name_lower or \
                            'offset' in property_name_lower or \
                            'margin' in property_name_lower:
                        size, = struct.unpack('<f', self.rgData[i])
                        propertyVal = PropertySet.half_inch_size_to_pixels(size)
                    elif 'langid' in property_name_lower:
                        lcid, =struct.unpack('<H', self.rgData[i])
                        propertyVal = '{}({})'.format(PropertySet.lcid_to_string(lcid), lcid)
                    elif 'languageid' in property_name_lower:
                        lcid, =struct.unpack('<I', self.rgData[i])
                        propertyVal = '{}({})'.format(PropertySet.lcid_to_string(lcid), lcid)
                    else:
                        if isinstance(self.rgData[i], list):
                            propertyVal = [str(i) for i in self.rgData[i]]
                        else:
                            propertyVal = str(self.rgData[i])
                self._formated_properties[propertyName] = propertyVal
        return self._formated_properties


    def __str__(self):
        result = ''
        for propertyName, propertyVal in self.get_properties().items():
            result += '{}{}: {}\n'.format(self.indent, propertyName, propertyVal)
        return result

    @staticmethod
    def half_inch_size_to_pixels(picture_width, dpi=96):
        # Number of pixels per half-inch
        pixels_per_half_inch = dpi / 2

        # Calculate the number of pixels
        pixels = picture_width * pixels_per_half_inch

        return int(pixels)

    @staticmethod
    def time32_to_datetime(time32):
        # Define the starting time (12:00 A.M., January 1, 1980, UTC)
        start = datetime(1980, 1, 1, 0, 0, 0)

        # Calculate the number of seconds represented by the Time32 value
        seconds = time32

        # Calculate the final datetime by adding the number of seconds to the starting time
        dt = start + timedelta(seconds=seconds)

        return dt


    @staticmethod
    def parse_filetime(filetime):
        # Define the number of 100-nanosecond intervals in 1 second
        intervals_per_second = 10 ** 7

        # Define the number of seconds between January 1, 1601 and January 1, 1970
        seconds_between_epochs = 11644473600

        # Calculate the number of seconds represented by the FILETIME value
        seconds = filetime / intervals_per_second

        # Calculate the number of seconds that have elapsed since January 1, 1970
        seconds_since_epoch = seconds - seconds_between_epochs

        # Convert the number of seconds to a datetime object
        dt = datetime(1970, 1, 1) + timedelta(seconds=seconds_since_epoch)

        return dt

    @staticmethod
    def lcid_to_string(lcid):
        return locale.windows_locale.get(lcid, 'Unknown LCID')


class PrtFourBytesOfLengthFollowedByData:
    def __init__(self, fh_onenote, propertySet):
        self.cb, = struct.unpack('<I', fh_onenote.read(4))
        self.Data, = struct.unpack('{}s'.format(self.cb), fh_onenote.read(self.cb))

    def __str__(self):
        return self.Data.hex()


class PropertyID:

    # 2.1.12 Properties
    _property_id_name_mapping = {
        0x08001C00: "LayoutTightLayout",
        0x14001C01: "PageWidth",
        0x14001C02: "PageHeight",
        0x0C001C03: "OutlineElementChildLevel",
        0x08001C04: "Bold",
        0x08001C05: "Italic",
        0x08001C06: "Underline",
        0x08001C07: "Strikethrough",
        0x08001C08: "Superscript",
        0x08001C09: "Subscript",
        0x1C001C0A: "Font",
        0x10001C0B: "FontSize",
        0x14001C0C: "FontColor",
        0x14001C0D: "Highlight",
        0x1C001C12: "RgOutlineIndentDistance",
        0x0C001C13: "BodyTextAlignment",
        0x14001C14: "OffsetFromParentHoriz",
        0x14001C15: "OffsetFromParentVert",
        0x1C001C1A: "NumberListFormat",
        0x14001C1B: "LayoutMaxWidth",
        0x14001C1C: "LayoutMaxHeight",
        0x24001C1F: "ContentChildNodesOfOutlineElement",
        0x24001C1F: "ContentChildNodesOfPageManifest",
        0x24001C20: "ElementChildNodesOfSection",
        0x24001C20: "ElementChildNodesOfPage",
        0x24001C20: "ElementChildNodesOfTitle",
        0x24001C20: "ElementChildNodesOfOutline",
        0x24001C20: "ElementChildNodesOfOutlineElement",
        0x24001C20: "ElementChildNodesOfTable",
        0x24001C20: "ElementChildNodesOfTableRow",
        0x24001C20: "ElementChildNodesOfTableCell",
        0x24001C20: "ElementChildNodesOfVersionHistory",
        0x08001E1E: "EnableHistory",
        0x1C001C22: "RichEditTextUnicode",
        0x24001C26: "ListNodes",
        0x1C001C30: "NotebookManagementEntityGuid",
        0x08001C34: "OutlineElementRTL",
        0x14001C3B: "LanguageID",
        0x14001C3E: "LayoutAlignmentInParent",
        0x20001C3F: "PictureContainer",
        0x14001C4C: "PageMarginTop",
        0x14001C4D: "PageMarginBottom",
        0x14001C4E: "PageMarginLeft",
        0x14001C4F: "PageMarginRight",
        0x1C001C52: "ListFont",
        0x18001C65: "TopologyCreationTimeStamp",
        0x14001C84: "LayoutAlignmentSelf",
        0x08001C87: "IsTitleTime",
        0x08001C88: "IsBoilerText",
        0x14001C8B: "PageSize",
        0x08001C8E: "PortraitPage",
        0x08001C91: "EnforceOutlineStructure",
        0x08001C92: "EditRootRTL",
        0x08001CB2: "CannotBeSelected",
        0x08001CB4: "IsTitleText",
        0x08001CB5: "IsTitleDate",
        0x14001CB7: "ListRestart",
        0x08001CBD: "IsLayoutSizeSetByUser",
        0x14001CCB: "ListSpacingMu",
        0x14001CDB: "LayoutOutlineReservedWidth",
        0x08001CDC: "LayoutResolveChildCollisions",
        0x08001CDE: "IsReadOnly",
        0x14001CEC: "LayoutMinimumOutlineWidth",
        0x14001CF1: "LayoutCollisionPriority",
        0x1C001CF3: "CachedTitleString",
        0x08001CF9: "DescendantsCannotBeMoved",
        0x10001CFE: "RichEditTextLangID",
        0x08001CFF: "LayoutTightAlignment",
        0x0C001D01: "Charset",
        0x14001D09: "CreationTimeStamp",
        0x08001D0C: "Deletable",
        0x10001D0E: "ListMSAAIndex",
        0x08001D13: "IsBackground",
        0x14001D24: "IRecordMedia",
        0x1C001D3C: "CachedTitleStringFromPage",
        0x14001D57: "RowCount",
        0x14001D58: "ColumnCount",
        0x08001D5E: "TableBordersVisible",
        0x24001D5F: "StructureElementChildNodes",
        0x2C001D63: "ChildGraphSpaceElementNodes",
        0x1C001D66: "TableColumnWidths",
        0x1C001D75: "Author",
        0x18001D77: "LastModifiedTimeStamp",
        0x20001D78: "AuthorOriginal",
        0x20001D79: "AuthorMostRecent",
        0x14001D7A: "LastModifiedTime",
        0x08001D7C: "IsConflictPage",
        0x1C001D7D: "TableColumnsLocked",
        0x14001D82: "SchemaRevisionInOrderToRead",
        0x08001D96: "IsConflictObjectForRender",
        0x20001D9B: "EmbeddedFileContainer",
        0x1C001D9C: "EmbeddedFileName",
        0x1C001D9D: "SourceFilepath",
        0x1C001D9E: "ConflictingUserName",
        0x1C001DD7: "ImageFilename",
        0x08001DDB: "IsConflictObjectForSelection",
        0x14001DFF: "PageLevel",
        0x1C001E12: "TextRunIndex",
        0x24001E13: "TextRunFormatting",
        0x08001E14: "Hyperlink",
        0x0C001E15: "UnderlineType",
        0x08001E16: "Hidden",
        0x08001E19: "HyperlinkProtected",
        0x08001E22: "TextRunIsEmbeddedObject",
        0x14001e26: "CellShadingColor",
        0x1C001E58: "ImageAltText",
        0x08003401: "MathFormatting",
        0x2000342C: "ParagraphStyle",
        0x1400342E: "ParagraphSpaceBefore",
        0x1400342F: "ParagraphSpaceAfter",
        0x14003430: "ParagraphLineSpacingExact",
        0x24003442: "MetaDataObjectsAboveGraphSpace",
        0x24003458: "TextRunDataObject",
        0x40003499: "TextRunData",
        0x1C00345A: "ParagraphStyleId",
        0x08003462: "HasVersionPages",
        0x10003463: "ActionItemType",
        0x10003464: "NoteTagShape",
        0x14003465: "NoteTagHighlightColor",
        0x14003466: "NoteTagTextColor",
        0x14003467: "NoteTagPropertyStatus",
        0x1C003468: "NoteTagLabel",
        0x1400346E: "NoteTagCreated",
        0x1400346F: "NoteTagCompleted",
        0x20003488: "NoteTagDefinitionOid",
        0x04003489: "NoteTagStates",
        0x10003470: "ActionItemStatus",
        0x0C003473: "ActionItemSchemaVersion",
        0x08003476: "ReadingOrderRTL",
        0x0C003477: "ParagraphAlignment",
        0x3400347B: "VersionHistoryGraphSpaceContextNodes",
        0x14003480: "DisplayedPageNumber",
        0x1C00349B: "SectionDisplayName",
        0x1C00348A: "NextStyle",
        0x200034C8: "WebPictureContainer14",
        0x140034CB: "ImageUploadState",
        0x1C003498: "TextExtendedAscii",
        0x140034CD: "PictureWidth",
        0x140034CE: "PictureHeight",
        0x14001D0F: "PageMarginOriginX",
        0x14001D10: "PageMarginOriginY",
        0x1C001E20: "WzHyperlinkUrl",
        0x1400346B: "TaskTagDueDate",
        0x1C001DE9: "IsDeletedGraphSpaceContent",
    }

    def __init__(self, fh_onenote):
        self.value, = struct.unpack('<I', fh_onenote.read(4))
        self.id = self.value & 0x3ffffff
        self.type = (self.value >> 26) & 0x1f
        self.boolValue = (self.value >> 31) & 1 == 1

    def get_property_name(self):
        return self._property_id_name_mapping[self.value] if self.value in self._property_id_name_mapping else 'Unknown'

    def __str__(self):
        return self.get_property_name()
