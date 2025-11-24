import struct
import uuid
from pyOneNote.FileNode import *


class Header:
    """MS-ONESTORE 2.3.1 Header 구조체
    OneNote 파일의 첫 1024바이트를 차지하는 헤더
    파일 메타데이터와 주요 구조체들의 파일 내 위치 참조를 포함"""
    # 파일 타입별 GUID 상수
    ONE_UUID = uuid.UUID('{7B5C52E4-D88C-4DA7-AEB1-5378D02996D3}')       # .one 파일
    ONETOC2_UUID = uuid.UUID('{43FF2FA1-EFD9-4C76-9EE2-10EA5722765F}')   # .onetoc2 파일
    GUID_FILE_FORMAT_UUID = uuid.UUID('{109ADD3F-911B-49F5-A5D0-1791EDC8AED8}')  # Revision Store 파일 포맷
    # 헤더 구조체 포맷 (1024바이트)
    HEADER_FORMAT = "<16s16s16s16sIIII8s8sIIQ8sIBBBB16sI12s12s12s12sQQ16sQ16sI12s12sIIII728s"

    # 파일 식별 및 버전 정보 (오프셋 0x000-0x03F)
    guidFileType = None                # 0x000: 파일 타입 식별자 (ONE/ONETOC2)
    guidFile = None                    # 0x010: 파일 고유 식별자
    guidLegacyFileVersion = None       # 0x020: 레거시 버전 (항상 0)
    guidFileFormat = None              # 0x030: 파일 포맷 식별자
    
    # 파일 버전 정보 (오프셋 0x040-0x04F)
    ffvLastCodeThatWroteToThisFile = None         # 0x040: 마지막으로 쓴 코드 버전
    ffvOldestCodeThatHasWrittenToThisFile = None  # 0x044: 가장 오래된 쓰기 코드 버전
    ffvNewestCodeThatHasWrittenToThisFile = None  # 0x048: 가장 최신 쓰기 코드 버전
    ffvOldestCodeThatMayReadThisFile = None       # 0x04C: 읽을 수 있는 가장 오래된 코드 버전
    
    # 레거시 파일 참조 (오프셋 0x050-0x087)
    fcrLegacyFreeChunkList = None         # 0x050: 레거시 Free Chunk List 참조 (8바이트)
    fcrLegacyTransactionLog = None        # 0x058: 레거시 Transaction Log 참조 (8바이트)
    cTransactionsInLog = None             # 0x060: 트랜잭션 로그 내 트랜잭션 개수
    cbLegacyExpectedFileLength = None     # 0x064: 레거시 예상 파일 길이
    rgbPlaceholder = None                 # 0x068: 플레이스홀더 (8바이트)
    fcrLegacyFileNodeListRoot = None      # 0x070: 레거시 FileNodeList 루트 참조 (8바이트)
    cbLegacyFreeSpaceInFreeChunkList = None  # 0x078: 레거시 Free Chunk List 여유 공간
    
    # 파일 상태 플래그 (오프셋 0x07C-0x07F)
    fNeedsDefrag = None            # 0x07C bit 0: 조각 모음 필요 여부
    fRepairedFile = None           # 0x07C bit 1: 파일 복구 여부
    fNeedsGarbageCollect = None    # 0x07C bit 2: 가비지 컬렉션 필요 여부
    fHasNoEmbeddedFileObjects = None  # 0x07C bit 3: 내장 파일 객체 없음 여부
    
    # 추가 메타데이터 (오프셋 0x080-0x1C7)
    guidAncestor = None               # 0x080: 상위 파일 GUID (16바이트)
    crcName = None                    # 0x090: 파일명 CRC (4바이트)
    
    # 주요 파일 구조체 참조 (오프셋 0x094-0x0E7)
    fcrHashedChunkList = None         # 0x094: Hashed Chunk List 참조 (12바이트)
    fcrTransactionLog = None          # 0x0A0: Transaction Log 참조 (12바이트)
    fcrFileNodeListRoot = None        # 0x0AC: FileNodeList 루트 참조 (12바이트)
    fcrFreeChunkList = None           # 0x0B8: Free Chunk List 참조 (12바이트)
    cbExpectedFileLength = None       # 0x0C4: 예상 파일 길이 (8바이트)
    cbFreeSpaceInFreeChunkList = None  # 0x0CC: Free Chunk List 여유 공간 (8바이트)
    
    # 버전 및 디버그 정보 (오프셋 0x0D4-0x117)
    guidFileVersion = None            # 0x0D4: 파일 버전 GUID (16바이트)
    nFileVersionGeneration = None     # 0x0E4: 파일 버전 세대 번호 (8바이트)
    guidDenyReadFileVersion = None    # 0x0EC: 읽기 거부 파일 버전 GUID (16바이트)
    grfDebugLogFlags = None           # 0x0FC: 디버그 로그 플래그 (4바이트)
    
    # 디버그 및 검증 참조 (오프셋 0x100-0x117)
    fcrDebugLog = None                # 0x100: 디버그 로그 참조 (12바이트)
    fcrAllocVerificationFreeChunkList = None  # 0x10C: 할당 검증 Free Chunk List (12바이트)
    
    # Build 번호 (오프셋 0x118-0x137)
    bnCreated = None              # 0x118: 생성 빌드 번호 (4바이트)
    bnLastWroteToThisFile = None  # 0x11C: 마지막 쓰기 빌드 번호 (4바이트)
    bnOldestWritten = None        # 0x120: 가장 오래된 쓰기 빌드 번호 (4바이트)
    bnNewestWritten = None        # 0x124: 가장 최신 쓰기 빌드 번호 (4바이트)
    
    # 예약 공간 (오프셋 0x128-0x3FF)
    rgbReserved = None            # 0x128: 예약 공간 (728바이트, 0으로 채워짐)

    def __init__(self, file):
        """헤더를 파일에서 읽어 파싱
        
        Args:
            file: OneNote 파일 객체 (1024바이트 읽기 가능해야 함)
        """
        self.guidFileType, \
        self.guidFile, \
        self.guidLegacyFileVersion, \
        self.guidFileFormat, \
        self.ffvLastCodeThatWroteToThisFile, \
        self.ffvOldestCodeThatHasWrittenToThisFile, \
        self.ffvNewestCodeThatHasWrittenToThisFile, \
        self.ffvOldestCodeThatMayReadThisFile, \
        self.fcrLegacyFreeChunkList, \
        self.fcrLegacyTransactionLog, \
        self.cTransactionsInLog, \
        self.cbLegacyExpectedFileLength, \
        self.rgbPlaceholder, \
        self.fcrLegacyFileNodeListRoot, \
        self.cbLegacyFreeSpaceInFreeChunkList, \
        self.fNeedsDefrag, \
        self.fRepairedFile, \
        self.fNeedsGarbageCollect, \
        self.fHasNoEmbeddedFileObjects, \
        self.guidAncestor, \
        self.crcName, \
        self.fcrHashedChunkList, \
        self.fcrTransactionLog, \
        self.fcrFileNodeListRoot, \
        self.fcrFreeChunkList, \
        self.cbExpectedFileLength, \
        self.cbFreeSpaceInFreeChunkList, \
        self.guidFileVersion, \
        self.nFileVersionGeneration, \
        self.guidDenyReadFileVersion, \
        self.grfDebugLogFlags, \
        self.fcrDebugLog, \
        self.fcrAllocVerificationFreeChunkList, \
        self.bnCreated, \
        self.bnLastWroteToThisFile, \
        self.bnOldestWritten, \
        self.bnNewestWritten, \
        self.rgbReserved, = struct.unpack(self.HEADER_FORMAT, file.read(1024))

        # GUID 필드를 little-endian UUID 객체로 변환
        self.guidFileType = uuid.UUID(bytes_le=self.guidFileType)
        self.guidFile = uuid.UUID(bytes_le=self.guidFile)
        self.guidLegacyFileVersion = uuid.UUID(bytes_le=self.guidLegacyFileVersion)
        self.guidFileFormat = uuid.UUID(bytes_le=self.guidFileFormat)
        self.guidAncestor = uuid.UUID(bytes_le=self.guidAncestor)
        self.guidFileVersion = uuid.UUID(bytes_le=self.guidFileVersion )
        self.guidDenyReadFileVersion = uuid.UUID(bytes_le=self.guidDenyReadFileVersion)

        # FileChunkReference64x32 (12바이트: stp 8바이트 + cb 4바이트) 변환
        # 이들은 파일 내 주요 구조체들의 위치를 가리킴
        self.fcrHashedChunkList = FileChunkReference64x32(self.fcrHashedChunkList)
        self.fcrTransactionLog = FileChunkReference64x32(self.fcrTransactionLog)
        self.fcrFileNodeListRoot = FileChunkReference64x32(self.fcrFileNodeListRoot)  # 가장 중요: 루트 노드 리스트
        self.fcrFreeChunkList = FileChunkReference64x32(self.fcrFreeChunkList)
        self.fcrDebugLog = FileChunkReference64x32(self.fcrDebugLog)
        self.fcrAllocVerificationFreeChunkList = FileChunkReference64x32(
            self.fcrAllocVerificationFreeChunkList)

        # FileChunkReference32 (8바이트: stp 4바이트 + cb 4바이트) 변환 - 레거시 지원
        self.fcrLegacyFreeChunkList = FileChunkReference32(self.fcrLegacyFreeChunkList)
        self.fcrLegacyTransactionLog = FileChunkReference32(self.fcrLegacyTransactionLog)
        self.fcrLegacyFileNodeListRoot = FileChunkReference32(self.fcrLegacyFileNodeListRoot)


    def convert_to_dictionary(self):
        """헤더 정보를 딕셔너리로 변환 (디버깅/출력용)
        
        Returns:
            dict: 헤더 필드들을 담은 딕셔너리 (rgbReserved 제외)
        """
        res = {}
        for key, item in self.__dict__.items():
            if not key.startswith('_') and not key == 'rgbReserved':
                if isinstance(item, uuid.UUID):
                    res[key] = str(item)
                elif isinstance(item, FileChunkReference64x32) or \
                    isinstance(item, FileChunkReference32) or \
                    isinstance(item, FileNodeChunkReference):
                    res[key] = str(item)
                else:
                    res[key] = item
        return res