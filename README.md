# AoE-MapCap

Tài liệu kỹ thuật đầy đủ (kiến trúc, bộ nhớ game, đồ hoạ, vận hành, lịch sử) ở thư mục [docs/](docs/README.md);
bối cảnh cho phiên làm việc mới ở [CLAUDE.md](CLAUDE.md).

Tự động lưu ảnh toàn bản đồ tại các mốc phút game 5, 10, 15, ... cho **AoE-HD**
(Age of Empires: Rise of Rome 1.0), đúng góc nhìn của người chơi hiện tại.

Hai chế độ vẽ:

- `full` (mặc định): dựng lại bản đồ bằng sprite thật của game (địa hình, viền địa hình,
  công trình, unit đúng hướng đứng, cây, mỏ...), ô 64x32 px, sương mù giống game.
  Bản đồ 144x144 ra ảnh 9216x4978 px; mặc định thu 50% (`--scale 0.5`).
- `mini`: kiểu minimap phóng to, nhẹ và nhanh.

Tool chạy **song song, bên ngoài game**, chỉ **đọc** bộ nhớ tiến trình game
(ReadProcessMemory). Không ghi bộ nhớ, không nạp DLL vào game.

## Yêu cầu

- Windows, Python 3.10+ (đã có trên máy này) cùng các gói: `pillow`, `numpy`, `psutil`
  (đã cài). Nếu máy khác: `pip install pillow numpy psutil`.
- Game để ở `D:\Game\AoE-HD` (đổi bằng `--game-dir` nếu khác; tool chỉ cần
  `data\interfac.drs` để lấy bảng màu).

Đã kiểm chứng ngày 2026-09-16 trên ván chơi đơn (empires.exe, bản đồ 144x144): offset, tên, màu, hướng bản đồ khớp minimap trong game.

## Bước 1: kiểm chứng offset (chỉ cần khi đổi bản game)

1. Mở game, vào một ván (đã thấy bản đồ).
2. Chạy `probe.bat` (hoặc `python probe.py`).
3. Gửi lại hai file `probe_output.txt` và `probe_map.png`, kèm một ảnh chụp
   minimap trong game cùng thời điểm để so hướng và màu.

## Cách dùng nhanh: AoE-MapCap.exe (một file, có giao diện)

`dist\AoE-MapCap.exe` là bản đóng gói một file, đã gói sẵn ffmpeg, không cần cài gì thêm.

- Mở exe (hộp UAC hiện một lần vì game chạy từ XArena có quyền Administrator).
- Chọn tuỳ chọn trên giao diện rồi bấm **Bắt đầu ghi**. Tool chờ game, khi vào trận sẽ ghi video diễn biến
  toàn bản đồ và chụp ảnh tĩnh chi tiết theo mốc phút. Hết trận (rời ra menu, thoát game, đồng hồ game đứng
  3 phút) tự chốt file mp4. Bấm **Dừng** để dừng và chốt video ngay.
- Video `.mp4` nằm trong thư mục **`Video\`** cạnh exe (đổi được trong giao diện), ảnh tĩnh trong `Video\Anh\`.
  Cấu hình đã chọn lưu ở `Video\_settings.ini`, nhật ký ở `Video\_mapcap.log`.

Hai chế độ ghi (chọn trên giao diện):

- **Ghi dữ liệu thô, dựng video sau trận** (mặc định): trong trận chỉ đọc game 25 mẫu/giây và ghi
  trạng thái vào `Video\Raw\*.aoerec` (vài KB mỗi mẫu, ~200-400 MB một trận 30 phút). Hết trận tự dựng
  video ở độ rộng đã chọn bằng nhiều tiến trình song song (1080p trận 30 phút khoảng 3-5 phút). Nút
  **Dựng lại video...** dựng lại bất kỳ file .aoerec nào với độ rộng (1920/2560/3840/9216 = kích cỡ gốc),
  FPS và tốc độ phát đang chọn. Dòng lệnh: `AoE-MapCap.exe --render-raw file.aoerec [out.mp4] --width=3840 --fps=25`.
- **Vẽ video ngay trong trận**: như bản cũ, xem được ngay khi hết trận nhưng tốn CPU hơn trong lúc chơi.

Tuỳ chọn trên giao diện:

| Tuỳ chọn | Ý nghĩa |
|---|---|
| FPS video | khung/giây của file mp4 (mặc định 25) |
| Nhịp đọc game | số lần đọc game và vẽ mỗi giây thật (mặc định 25, bằng FPS video để mượt). Đọc ở luồng riêng ~15-30 ms, vẽ ~8 ms ở 1080p |
| Độ rộng video | 1280 / 1600 / 1920 / 2560 / 3840 px, chiều cao theo bản đồ |
| Tua nhanh | 1 = thời gian thật, 8 = trận 40 phút thành video 5 phút |
| Ảnh tĩnh mỗi N phút | 0 để tắt; ảnh vẽ ở tiến trình riêng nên không làm chậm video |
| Mã hoá | auto thử GPU (NVENC, Quick Sync, AMF) rồi mới dùng CPU; thử ở đúng kích thước khung, nên dựng ở độ rộng gốc 9216 luôn dùng CPU (libx264) vì mã hoá phần cứng chỉ nhận tới 4096 px ngang, chậm hơn nhiều |
| Viền trắng mờ | đường viền ranh giới bản đồ, nằm ngoài mép 2 px nên không đè lên địa hình |
| Sương mù | Làm tối đều (mặc định) hoặc Lưới chấm như game (hợp khi dựng ở độ rộng gốc 9216) |

Xem video có phóng to: VLC bấm `Z` để đổi tỉ lệ hoặc Tools > Effects and Filters > Video Effects > Geometry >
Interactive Zoom; tiện hơn là PotPlayer (Ctrl + lăn chuột để phóng, kéo chuột để di chuyển) hoặc mpv
(`Alt + +`/`Alt + -` phóng, `Alt + mũi tên` di chuyển). Muốn chi tiết hơn khi phóng, tăng độ rộng video lên 2560.

Dòng lệnh: `AoE-MapCap.exe --nogui [--fps=25 --capture=25 --width=1920]` chạy với cấu hình đã lưu.
Mã nguồn quản lý bằng git ngay trong thư mục này (`git log`).

Trong lúc ghi, file mang tên `*.part.mp4` (tắt đột ngột vẫn xem được). Khi chốt trận, tool đóng gói lại
thành `.mp4` chuẩn. Lần mở sau tool tự cứu các file `.part.mp4` còn sót.

Dựng lại exe: `pip install pyinstaller` rồi
`python -m PyInstaller --onefile --windowed --uac-admin --name AoE-MapCap --add-binary "vendor/ffmpeg.exe;." run_app.py`
(ffmpeg trong `vendor\` là bản 7.1 essentials của gyan.dev lấy từ gói imageio-ffmpeg).

## Bước 2: chạy tự động (bản Python, chỉ chụp ảnh)

```
run_mapcap.bat
```

hoặc

```
python -m mapcap.main --interval 5 --out "D:\Game\AoE-HD\Screenshot\FullMap"
```

Tool chờ game chạy, khi vào ván sẽ theo đồng hồ game và lưu ảnh tại mỗi mốc
`interval` phút (mặc định 5). Tên file: `YYYY-MM-DD_HHMMSS_tranN_05p.png`.

Tuỳ chọn:

| Tuỳ chọn | Ý nghĩa |
|---|---|
| `--interval 2` | mốc mỗi 2 phút game |
| `--mode mini` | vẽ kiểu minimap phóng to thay cho sprite thật |
| `--scale 1` | chế độ full: giữ kích cỡ gốc (mặc định 0.5) |
| `--save-snap` | lưu thêm file .snap để vẽ lại sau bằng `render_snap.py` |
| `--tile 24` | ô rộng 24 px (ảnh to hơn; mặc định 16) |
| `--flat` | không dịch ô theo độ cao |
| `--no-units` | chỉ vẽ địa hình |
| `--fog-dim 1` | không làm tối vùng ngoài tầm nhìn (giống minimap game); mặc định 0.65 |
| `--now` | chụp ngay một ảnh rồi thoát (để thử) |

Nếu game chạy với quyền Administrator thì tool cũng phải chạy Administrator
(chuột phải `run_mapcap.bat`, Run as administrator).

## Nội dung ảnh

Cây rừng và phần lớn mỏ không nằm trong danh sách unit của người chơi mà gắn với từng ô đất; tool đọc thêm
danh sách theo ô để rừng dày đúng như game. Cây bị đốn hết máu chuyển sang hình thân cây đổ (đồ hoạ
"dying" trong empires.dat) và khi hết gỗ thành gốc cây; trạng thái này được đọc lại mỗi 2 giây.

Chế độ full: giống màn chơi (texture địa hình, viền chuyển tiếp, công trình theo thời đại,
unit theo hướng quay và màu quân, bóng đổ nằm sẵn trong sprite). Vùng ngoài tầm nhìn tối 43% như game,
vùng chưa khám phá đen; mặt nạ sương mù trong video dựng từ chính hình thoi ô đã vẽ nên khớp cả trên đồi.
Vật thể trong sương mù vẽ theo đúng cơ chế của game: game tạo "doppelganger" (đối tượng loại 25, 0xB0 byte,
+0xC = người chơi ghi nhớ, +0x94 unitdef gốc, +0x98 id chủ gốc, +0xAC id gốc) khi ô có công trình/cây/mỏ rơi vào
sương mù và tự huỷ khi ô được nhìn lại; tool đọc thẳng các đối tượng này từ danh sách vật thể của ô (DoppelTracker
quét các ô vừa mất tầm nhìn, StaticObjects bổ sung khi quét toàn bộ) và vẽ chúng mờ thay cho vật thể thật.
Đã đối chiếu trên trận thật (2026-10-07): số doppelganger tool ghi khớp số đếm độc lập trong bộ nhớ game ở mọi
mốc 20 giây. Đối tượng loại 25 nằm trong danh sách unit của người chơi (thấy ở máy AI) không phải ký ức của ta nên bị bỏ.
Công trình có cờ fog_visible = 0 nên trong sương mù chỉ hiện qua doppelganger, đúng như game. Nếu file thô không có
doppelganger nào (dữ liệu cũ) thì dựng video dùng mô phỏng dự phòng (ghi nhớ công trình đã thấy).
Chưa có: khung hình chuyển động của unit (dùng khung đứng), nước động.

Chế độ mini:

- Địa hình theo màu minimap của game, có bóng dốc và dịch theo độ cao.
- Vùng chưa khám phá: đen. Vùng đã khám phá nhưng ngoài tầm nhìn: tối đi.
- Công trình: hình chữ nhật màu quân; unit sống: chấm tròn; tài nguyên: ô vuông nhỏ
  theo màu minimap của loại đó. Chỉ vẽ những gì người chơi hiện tại nhìn thấy,
  đúng như minimap trong game.
- Dòng đầu ảnh: thời gian game, kích cỡ bản đồ, tên người chơi và số đối tượng.

## Cấu trúc

- `mapcap/offsets.py`: toàn bộ offset bộ nhớ, có chú thích nguồn gốc.
- `mapcap/memory.py`: tìm tiến trình và đọc bộ nhớ.
- `mapcap/game.py`: đọc snapshot (địa hình, tầm nhìn, người chơi, unit).
- `mapcap/render.py`: vẽ kiểu minimap.
- `mapcap/render_full.py`: vẽ bằng sprite thật; `mapcap/slp.py` giải mã SLP; `mapcap/dat.py` đọc empires.dat.
- `render_snap.py`: vẽ lại từ file .snap đã lưu.
- `mapcap/rawrec.py`: định dạng dữ liệu thô .aoerec; `mapcap/offline.py`: dựng video song song từ dữ liệu thô;
- `mapcap/video_render.py`: bộ vẽ tăng dần cho video; `mapcap/recorder.py`: ghi qua ffmpeg;
  `mapcap/engine.py`: vòng lặp ghi dùng chung; `mapcap/gui.py`: giao diện tkinter; `mapcap/app.py`: bản dòng lệnh cũ.
- `mapcap/main.py`: vòng lặp theo mốc phút.
- `probe.py`: kiểm chứng offset khi đang trong game.
- `re/`: script dịch ngược tĩnh đã dùng để tìm offset (capstone).

## Lưu ý

- meme.dll của AoE-HD là anti-hack. Tool chỉ mở handle đọc, không sửa gì, nhưng
  không thể bảo đảm tuyệt đối anti-hack không phản ứng. Nên thử ở ván chơi đơn trước.
- Offset áp dụng cho EMPIRESX.EXE, EMPIRESX_HD.EXE, EMPIRESX_HDR.EXE, empires.exe
  và 4 file patch\EMPIRESX1..4.EXE của bản AoE-HD 0.5. Bản khác cần kiểm lại.
