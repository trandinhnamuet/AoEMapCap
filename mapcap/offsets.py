"""Offset bộ nhớ của EMPIRESX.EXE (AoE-HD, Rise of Rome 1.0 bản GameTV).

Toàn bộ offset dưới đây được suy ra bằng dịch ngược tĩnh file exe (xem thư mục re/).
Đã kiểm tra: EMPIRESX.EXE, EMPIRESX_HD.EXE, EMPIRESX_HDR.EXE, empires.exe và 4 file
patch/EMPIRESX1..4.EXE có cùng mã lệnh tại các vị trí liên quan, nên dùng chung offset.
Exe không bật ASLR, image base cố định 0x400000.

Ký hiệu: [X] = giá trị tại địa chỉ X.
"""

# ---- biến toàn cục ----------------------------------------------------------
SETTINGS_PTR = 0x585E88          # dword -> đối tượng "game settings"
VISIBILITY_ROWS = 0x7D70C8       # mảng con trỏ hàng (theo y); mỗi hàng: dword/ô = mask tầm nhìn
                                 # low word: người chơi đang nhìn thấy; high word: đã khám phá

# ---- SETTINGS ----------------------------------------------------------------
SETTINGS_GLOBAL = 0x3F4          # -> GLOBAL (thế giới game); 0 khi chưa vào trận
# Thiết lập ván (RE 2026-10-09: hàm ghi log "game started" 0x506D60 và các getter 0x507990..0x507B60, 0x41BF50..):
SETTINGS_READ_START = 0x980      # đọc một khối [0x980, 0xAF0) + 2 dword ở +0x30/+0x34
SETTINGS_READ_END = 0xAF0
SETTINGS_RANDOM_GAME = 0x30      # int32 "randomgame"
SETTINGS_RANDOM_MAP = 0x34       # int32 "randommap"
SETTINGS_FULL_TECH = 0x985       # byte "fulltech"
SETTINGS_TEAMS = 0x994           # byte[người chơi-1]: đội + 1 (log in ra team-1; 0 = không đội)
SETTINGS_CIVS = 0xA94            # byte[người chơi-1]: nền văn minh trong thiết lập (chưa đối chiếu giá trị "ngẫu nhiên")
SETTINGS_PLAYERS = 0xAC4         # byte[người chơi-1]: "players=" trong log (chưa rõ nghĩa)
SETTINGS_MAP_SIZE = 0xA7C        # int32 0..5 -> chuỗi 10611..10616 (Rất nhỏ .. Siêu lớn)
SETTINGS_MAP_TYPE = 0xA80        # int32 0..8 -> chuỗi 10602.. (Quần đảo nhỏ, Quần đảo lớn, Bờ biển, Nội địa, Đất cao,
                                 #   Lục địa, Địa Trung Hải, Đồi cao, Cửa biển hẹp)
SETTINGS_VICTORY = 0xA8C         # int32 0..9 điều kiện thắng (0 Standard? log: Default/Standard/Time(%d)/Score(%d))
SETTINGS_VICTORY_VALUE = 0xA90   # int32 tham số (thời gian / điểm)
SETTINGS_REVEAL_MAP = 0xAD9      # byte
SETTINGS_RESOURCES = 0xADC       # int32 0 mặc định, 1 thấp, 2 vừa, 3 cao
SETTINGS_START_AGE = 0xAE0       # int32 0 mặc định, 1 đồ đá, 2 công cụ, 3 đồ đồng, 4 đồ sắt
SETTINGS_FLAG_AE4 = 0xAE4        # byte (chưa rõ)
SETTINGS_DEATHMATCH = 0xAE5      # byte DeathMatch

# ---- GLOBAL (thế giới) -------------------------------------------------------
GLOBAL_TIME_MS = 0x04            # uint32, thời gian game tính bằng ms (đồng hồ hh:mm:ss = /1000)
GLOBAL_SPEED = 0x18              # float, tốc độ game
GLOBAL_MAPINFO = 0x28            # -> MAPINFO
GLOBAL_PLAYER_COUNT = 0x3C       # int16, số người chơi kể cả Gaia (index 0)
GLOBAL_PLAYERS = 0x40            # -> mảng con trỏ PLAYER
GLOBAL_GAMEINFO = 0x58           # -> đối tượng thông tin ván (tên người chơi ở [+0x14])
GLOBAL_CUR_PLAYER_ID = 0x7C      # int16, id người chơi đang điều khiển (người xem)
GLOBAL_GAME_OVER = 0x1D          # byte: 1 khi ván kết thúc (ghi ở 0x52088B/0x5208D0; log "GAME OVER!" 0x520711 đọc nó)

# ---- GAMEINFO names object: obj = [[GLOBAL+0x58]+0x14] --------------------------
GAMEINFO_NAMES_OBJ = 0x14
NAMES_OWN_INDEX = 0x10E0         # int32: index của chính mình
NAMES_OWN_NAME = 0x10F8          # char[]: tên của chính mình
NAMES_TABLE = 0x12C8             # -> bảng tên, mỗi tên 0x80 byte
NAMES_COUNT = 0x12D8             # uint16
NAMES_ENTRY_SIZE = 0x80

# ---- MAPINFO -----------------------------------------------------------------
MAP_SIZE_X = 0x08                # int16, số cột (trục của unit+0x38)
MAP_SIZE_Y = 0x0C                # int16, số hàng (trục của unit+0x3C)
MAP_TERRAIN_DEFS = 0xB4          # bảng định nghĩa địa hình, stride 0x198
TERRAIN_DEF_SIZE = 0x198
TERRAIN_MINIMAP_COLORS = (0x0, 0x1, 0x2)   # 3 byte màu palette: [+b4], [+b5], [+b6]
MAP_TILE_ROWS = 0x8D8C           # -> mảng con trỏ hàng ô (theo y); mỗi ô 0x18 byte
MAP_REVEAL_FLAG = 0x8DB8         # byte: bỏ sương mù (reveal map)
MAP_REVEAL_FLAG2 = 0x8DB9
TILE_SIZE = 0x18
TILE_UNITS_LIST = 0x10           # -> danh sách unit đứng trên ô
TILE_SHAPE = 0x04                # byte 0..16: dạng dốc của ô (0 = phẳng)
TILE_TERRAIN = 0x05              # byte: bit 0-4 = id địa hình, bit 5-7 = độ cao
TILE_BORDER = 0x06               # byte: bit 0-3 = id viền (bảng border trong empires.dat), bit 4-7 = cấu hình 0..11
TILE_DRAW_X = 0x00               # int16 toạ độ vẽ ô do game tính ((x+y)*32)
TILE_DRAW_Y = 0x02               # int16 ((y-x)*16 - 16*độ cao - 16 với vài dạng dốc)

# Dạng dốc -> chọn màu minimap nào trong 3 màu (0 -> +b4, 1 -> +b5, 2 -> +b6),
# lấy từ bảng nhảy trong diam_map::draw_tile.
SHAPE_TO_COLOR_INDEX = {0: 1, 1: 2, 2: 0, 3: 0, 4: 2, 5: 2, 6: 0, 7: 2, 8: 2, 9: 2,
                        10: 0, 11: 0, 12: 2, 13: 2, 14: 0, 15: 2, 16: 0}

# ---- PLAYER ------------------------------------------------------------------
PLAYER_UNITDEFS = 0x24           # -> mảng con trỏ UNITDEF theo DAT id (số lượng int16 ở +0x22)
PLAYER_ATTR_COUNT = 0x4C         # int16 số thuộc tính (RE: set_attribute 0x45DEF0 so sánh với trường này)
PLAYER_ATTRS = 0x50              # -> float[] thuộc tính: 0 thực, 1 gỗ, 2 đá, 3 vàng (trùng loại chi phí trong DAT),
                                 #    4 chỗ dân còn, 6 thời đại, 11 dân số hiện tại, 20 số kill (chuẩn Genie, cần xác minh)
PLAYER_CIV = 0x109               # byte id nền văn minh (0 Gaia, 1 Egyptian ... 7 Phoenician ... 16 Macedonian); xác nhận trận thật
PLAYER_RESEARCH = 0x224          # -> đối tượng nghiên cứu (RE: Player ctor 0x4F269D tạo ở 0x4ECA95)
RESEARCH_STATES = 0x00           #    +0 -> mảng entry 8 byte theo id công nghệ (calloc(count, 8))
RESEARCH_COUNT = 0x04            #    +4 int16 số công nghệ (127 với RoR)
RESEARCH_TABLE = 0x08            #    +8 -> bảng công nghệ của thế giới (GLOBAL+0x104)
RESEARCH_ENTRY_SIZE = 8
RESEARCH_ENTRY_STATE = 4         #    int16: 0 chưa mở, 1 có thể nghiên cứu, 2 đang nghiên cứu, 3 đã xong
RESEARCH_STATE_DONE = 3          #    (0x4ECD0D ghi 3 khi hoàn thành; 0x4ED3D0 ghi 2 khi bắt đầu)
RESEARCH_STATE_ACTIVE = 2
RESEARCH_ENTRY_PROGRESS = 0      #    float giây đã nghiên cứu; 0x4ECE34 cộng dồn, xong khi >= thời gian của công nghệ
                                 #    (bản ghi 0x3C byte của bảng thế giới, int16 +0x1E = thời gian DAT)
PLAYER_READ_SIZE = 0x240
ATTR_FOOD, ATTR_WOOD, ATTR_STONE, ATTR_GOLD = 0, 1, 2, 3
ATTR_POP_ROOM, ATTR_AGE, ATTR_POP = 4, 6, 11
ATTR_KILLS = 20                  # xác minh trận thật 2026-10-07 (tăng khi hạ unit địch)
ATTR_DEATHS = None               # không có trực tiếp: loss = ATTR_KILLS - ATTR_KILL_RATIO (xác nhận 66 - 33 = 33)
ATTR_RAZINGS = 43                # công trình địch đã phá
ATTR_KILL_RATIO = 44             # kill - loss
ATTR_GOLD_COLLECTED = 49         # vàng đã khai thác cả trận (khớp bảng tổng kết 750); Tribe_Player::add_attribute 0x4F9040 cộng vào khi là vàng
ATTR_TRIBUTE_GIVEN = 53          # cống nạp đã cho (Achievements > Economy > Tribute Given); RE 0x4EB450: người cho +=, người nhận -=
ATTR_READ_MAX = 64
PLAYER_LIST_A = 0x28             # -> danh sách unit (header; [+4] = node đầu)
PLAYER_LIST_B = 0x30             # -> danh sách unit thứ hai (vẽ trước trên minimap)
PLAYER_GLOBAL = 0x3C             # -> GLOBAL
PLAYER_ID = 0x4A                 # int16
PLAYER_TYPE = 0x80               # = PLAYER_GAME_STATUS (tên cũ; header .aoerec lưu ở trường 'ptype')
PLAYER_GAME_STATUS = 0x80        # byte: 0 đang chơi, 1 thắng, 2 thua. RE 2026-10-09: Player vtable+4 = set_game_status
                                 # 0x45CB90 (ghi +0x80; trạng thái 2 khi chưa đầu hàng báo sự kiện 6 "bị đánh bại");
                                 # log "GAME OVER!" 0x520746: +0x80 == 1 -> "Player #%d Won" ngược lại "Lost"
PLAYER_RESIGNED = 0x81           # byte: 1 = đã đầu hàng (vtable+8 = resign 0x45CBF0: đặt +0x81 = 1, set_game_status(2))
PLAYER_DIPLOMACY = 0xB0          # int32[..] thái độ với từng người chơi
PLAYER_EXPLORED_MASK = 0xD4      # dword: mask so với ô tầm nhìn -> đã khám phá
PLAYER_VISIBLE_MASK = 0xD8       # dword: mask -> đang nhìn thấy
PLAYER_COLOR_PTR = 0x10C         # -> struct màu; [+0x25] = màu minimap (palette index)
PLAYER_COLOR_MINIMAP = 0x25
PLAYER_NAME_HOLDER = 0x34        # -> struct; [+0x1C] có thể là char* tên (chưa chắc, probe)
PLAYER_SELECTED = 0x138          # unit đang chọn (tối đa 25)
PLAYER_SELECTED_COUNT = 0x1A0

# Danh sách liên kết: header -> [+4] node đầu; node: [0] = unit, [+4] = node kế
LIST_FIRST = 0x04
NODE_UNIT = 0x00
NODE_NEXT = 0x04

# ---- UNIT --------------------------------------------------------------------
UNIT_ID = 0x04                   # int32
UNIT_DEF = 0x08                  # -> UNITDEF
UNIT_OWNER = 0x0C                # -> PLAYER
UNIT_FLAGS = 0x36                # byte; bit0 bật ở unit của người chơi (ý nghĩa chưa rõ), KHÔNG dùng để ẩn
UNIT_HP = 0x30                   # float máu hiện tại
UNIT_ANGLE = 0x35                # byte hướng quay 0..7 (góc radian ở +0x9C)
UNIT_POS_X = 0x38                # float, cột
UNIT_POS_Y = 0x3C                # float, hàng
UNIT_POS_Z = 0x40                # float (độ cao), suy đoán
UNIT_STATUS = 0x48               # byte trạng thái: 2 bình thường, >=3 đang chết / cây đã đốn
UNIT_TYPE_BYTE = 0x4E            # byte loại đối tượng (25 = doppelganger, còn lại trùng type của unitdef)
UNIT_RES_AMOUNT = 0x44           # float lượng tài nguyên đang chứa: gỗ của cây, thực của xác thú/bụi quả/ruộng,
                                 # vàng/đá của mỏ, đồ dân đang mang (RE 2026-10-09: 0x4A8950 lấy từ def+0x70[k] khi
                                 # def+0x88[k] == 0, loại ở def+0x6A[k])
UNIT_RES_TYPE = 0x4C             # int16 loại tài nguyên đang chứa (0 thực, 1 gỗ, 2 đá, 3 vàng; -1 không có)
UNIT_READ_SIZE = 0x60
UNIT_SPRITE_LIST = 0x18          # -> danh sách sprite (RE: RGE_Object init 0x4A8200, vẽ 0x4A8A60 gọi [list]->vtable+0xC)

# ---- danh sách sprite: list {vtable, +4 node đầu}; node 12 byte {+0 sprite node, +4 thứ tự (byte), +8 node kế}
SPRLIST_HEAD = 0x04
SPRNODE_SIZE = 0x0C
SPRNODE_OBJ = 0x00
SPRNODE_ORDER = 0x04
SPRNODE_NEXT = 0x08
# sprite node: {vtable, +4 RGE_Sprite*, +8 kiểu (1 tĩnh 0x14 byte, 2 động 0x28 byte), +0xC/+0x10 lệch vẽ,
#               động: +0x14 int16 khung hiện tại, +0x18 float bộ đếm thời gian khung, +0x20 int16 khung cuối}
SPRITENODE_SPRITE = 0x04
SPRITENODE_KIND = 0x08
SPRITENODE_FRAME = 0x14
SPRITENODE_READ_SIZE = 0x28
# RGE_Sprite (đồ hoạ trong bộ nhớ): +0 tên file, +0x10 int32 slp id, +0x48 tên, +0x5E int16 số khung,
#   +0x60 int16 số hướng, +0x68 float tốc độ khung, +0x6C float trễ lặp, +0x70 cờ (bit0 động), +0x72 int16 id đồ hoạ DAT
SPRITE_SLP = 0x10
SPRITE_FRAMES = 0x5E
SPRITE_ANGLES = 0x60
SPRITE_GRAPHIC_ID = 0x72
SPRITE_READ_SIZE = 0x78
UNITDEF_HP = 0x26                # int16 máu tối đa (RGE_Object init: unit+0x30 = def+0x26)

# ---- doppelganger: bản ghi nhớ của một người chơi về vật thể đã thấy, game tạo khi ô vật thể rơi vào
# sương mù và tự huỷ khi người đó nhìn lại ô (RE: ctor 0x436500, update 0x436B00, vẽ 0x451FD0).
# Đối tượng 0xB0 byte; +0xC = người chơi GHI NHỚ (không phải chủ vật thể gốc); +8 = unitdef của vật thể gốc.
UNIT_KIND_DOPPEL = 25
UNIT_DOPPEL_ORIG = 0x8C          # -> unit gốc (0 khi gốc đã chết)
UNIT_DOPPEL_ORIG_DEF = 0x94      # -> unitdef gốc lúc tạo (hình để vẽ)
UNIT_DOPPEL_ORIG_OWNER = 0x98    # int32 id người chơi sở hữu vật thể gốc (màu quân)
UNIT_DOPPEL_VIS_PTR = 0x9C       # -> ô tầm nhìn của ô chứa nó
UNIT_DOPPEL_SEEN_MASK = 0xA4     # bit id người chơi khác cũng có bản ghi nhớ cùng gốc
UNIT_DOPPEL_ORIG_UID = 0xAC      # id vật thể gốc (-1 khi gốc đã chết)
UNIT_DOPPEL_READ_SIZE = 0xB0

# ---- UNITDEF -----------------------------------------------------------------
UNITDEF_TYPE = 0x04              # byte: 10 eye candy, 20 flag, 25 doppelganger, 30 dead/fish,
                                 # 40 bird, 60 projectile, 70 living, 80 building, 90 tree
UNITDEF_NAME = 0x08              # -> char* tên nội bộ
UNITDEF_LANG_NAME = 0x0C         # int16 id chuỗi tên trong language.dll (probe: Man = 5131)
UNITDEF_LANG_CREATE = 0x0E       # int16 id chuỗi mô tả (probe: 6131)
UNITDEF_ID = 0x10                # int16 DAT id (probe: Man = 83, Town_Center1 = 109)
UNITDEF_ID2 = 0x12
UNITDEF_CLASS = 0x14             # int16 class (probe: 1 artifact, 3 building, 4 civilian, 8 stone mine)
UNITDEF_FOG_VISIBLE = 0x65       # byte: vẫn hiện trên minimap khi ô chỉ "đã khám phá"
UNITDEF_MINIMAP_MODE = 0x8E      # byte 0..3: 0 không vẽ, 3 = dùng màu riêng
UNITDEF_MINIMAP_COLOR = 0x90     # byte palette index (khi mode = 3)
UNITDEF_READ_SIZE = 0xA0
# Chỉ số (RE 2026-10-09 từ các hàm nạp empires.dat: loại 10 = 0x441FA0, 20 = 0x43F640, 30 = 0x4416D0,
# 40 = 0x43ED70, 50 = 0x43FC30, 70 = 0x4EEF40; hàm đọc file 0x46CA00). Mỗi người chơi có bản sao def riêng,
# công nghệ sửa trực tiếp bản sao đó -> đọc ở đây là chỉ số đã nâng cấp.
UNITDEF_LOS = 0x28               # float tầm nhìn
UNITDEF_SPEED = 0xB8             # float tốc độ chạy (loại >= 20)
UNITDEF_BASE_ARMOR = 0x100       # byte giáp gốc (loại >= 50)
UNITDEF_ARMOR_COUNT = 0x102      # int16 số mục giáp, UNITDEF_ARMORS -> mảng {int16 class, int16 amount}
UNITDEF_ARMORS = 0x104
UNITDEF_ATTACK_COUNT = 0x108     # int16 số mục công, UNITDEF_ATTACKS -> mảng {int16 class, int16 amount}
UNITDEF_ATTACKS = 0x10C
UNITDEF_MAX_RANGE = 0x114        # float
UNITDEF_RELOAD = 0x120           # float thời gian giữa hai đòn (giây)
UNITDEF_ACCURACY = 0x126         # int16 %
UNITDEF_MIN_RANGE = 0x138        # float
UNITDEF_DISP_MELEE_ARMOR = 0x13C # int16 giáp hiển thị gốc (= max(giáp gốc, giáp lớp != 3) lúc nạp DAT)
UNITDEF_DISP_ATTACK = 0x13E      # int16 công hiển thị gốc
UNITDEF_DISP_RANGE = 0x140       # float tầm hiển thị gốc
UNITDEF_DISP_RELOAD = 0x144      # float
UNITDEF_COSTS = 0x148            # 3 x {int16 loại, int16 số lượng, int16 cờ} (loại >= 70)
UNITDEF_TRAIN_TIME = 0x15A       # int16 giây
UNITDEF_DISP_PIERCE = 0x160      # int16 giáp xuyên hiển thị gốc (= max giáp lớp 3)
ARMOR_CLASS_PIERCE = 3           # lớp giáp/công 3 = xuyên (tên, đạn); khác = cận chiến
UNITDEF_STATS_SIZE = 0x168

UNIT_TYPE_LIVING = 70
UNIT_TYPE_BUILDING = 80
UNIT_TYPE_TREE = 90
