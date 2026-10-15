# AoE-MapCap

**[⬇ Tải bản Windows mới nhất (AoE-MapCap-win64.zip)](https://github.com/trandinhnamuet/AoEMapCap/releases/latest/download/AoE-MapCap-win64.zip)**
· [Các phiên bản và có gì mới](https://github.com/trandinhnamuet/AoEMapCap/releases)
· [Kiểm tra file tải về](#kiểm-tra-file-tải-về)

Ghi lại trận **AoE-HD** và **AOE1R** (Age of Empires: Rise of Rome 1.0, cả bản 1024×768) và **xem lại như replay Liên Minh Huyền Thoại**: tua tới/lui,
đổi tầm nhìn từng đội (F1/F2/F3), bảng tỉ số, công nghệ, bấm vào unit xem máu/công/giáp, zoom nét tới từng pixel game,
toàn màn hình, đưa chuột ra mép để cuộn. Video mp4 toàn bản đồ chỉ xuất khi bạn cần.

Giải nén zip là chạy, không cần cài đặt:

- `AoE-MapCap.exe`: mở lên là tự bắt đầu ghi (chờ game), cứ thế vào game; mỗi trận lưu vào `Video\Raw\*.aoerec`. Thẻ **Trận đã ghi**
  liệt kê các trận (người chơi, quân, kết quả, 4v4/1v1, thể thức, bản đồ), bấm đúp để xem replay, **Xuất video...**
  khi cần file mp4.

Tool chạy **song song, bên ngoài game**, chỉ **đọc** bộ nhớ tiến trình game (ReadProcessMemory). Không ghi bộ nhớ,
không nạp DLL vào game. Cần thư mục game AoE-HD hoặc AOE1R trên máy để lấy đồ hoạ.

## Cập nhật

Từ v3, mỗi khi mở (và 6 giờ một lần) app tự xem có bản mới chưa. Có bản mới thì hiện thanh **Có bản mới vN**:
**Có gì mới** xem thay đổi, **Cập nhật** để app tự tải bản mới (cả `AoE-MapCap.exe` và `AoE-Replay.exe` nếu có trong cùng thư
mục), kiểm mã SHA-256, thay file rồi tự mở lại; **Để sau** thì dùng tiếp bản đang có. Đang ghi trận hoặc đang xuất
video thì app chờ xong việc mới cập nhật. Không có mạng vẫn dùng bình thường. Bản quá cũ (đã ngừng hỗ trợ) chỉ còn
nút Cập nhật / Thoát. Bản v1, v2 chưa có tính năng này: tải v3 bằng tay một lần. Mỗi bản có gì mới:
[trang Releases](https://github.com/trandinhnamuet/AoEMapCap/releases).

## Thống kê sử dụng

Từ v6, mỗi lần mở app (có mạng) và mỗi trận ghi xong, app gửi một lượt thống kê lên Cloudflare: **mã máy ngẫu
nhiên** (tạo lần đầu, lưu ở `%APPDATA%\AoE-MapCap\install_id`), **tên người chơi** (nickname của người ghi, lấy từ
trận đã ghi gần nhất), phiên bản; máy nhận ghi thêm địa chỉ IP. Không gửi nội dung trận đấu hay dữ liệu nào khác.
Mục đích: biết bao nhiêu máy, những ai đang dùng. Tắt trong thẻ **Cài đặt** (bỏ ô "Gửi thống kê sử dụng"). Mã nguồn phía nhận: `telemetry/`.

## Kiểm tra file tải về

Bản Windows được build hoàn toàn trên GitHub Actions ([.github/workflows/release.yml](.github/workflows/release.yml))
từ mã nguồn công khai của repo này bằng chính `build.py`, không build trên máy cá nhân nào. Mỗi
Release có chứng nhận nguồn gốc (build provenance) do GitHub ký:

```
gh attestation verify AoE-MapCap-win64.zip -R trandinhnamuet/AoEMapCap
gh attestation verify AoE-MapCap.exe -R trandinhnamuet/AoEMapCap
```

Mã băm SHA-256 nằm trong `SHA256SUMS.txt` (trong zip) và `AoE-MapCap-win64.zip.sha256` (trên trang Release);
`VERSION.txt` ghi commit nguồn. Exe chưa ký số nên Windows SmartScreen có thể cảnh báo lần đầu.

Đăng phiên bản mới (người duy trì): `git tag v2 && git push origin v2`.

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

`dist\AoE-MapCap.exe` là bản đóng gói một file, không cần cài gì thêm.

- Mở exe (hộp UAC hiện một lần vì game chạy từ XArena có quyền Administrator): tool tự bắt đầu ghi, không cần bấm **● Bắt đầu ghi** (tắt được trong thẻ Cài đặt). Tool chờ
  game; mỗi trận được ghi thành dữ liệu `Video\Raw\*.aoerec` (25 lần đọc/giây, ~10-40 MB một trận từ 12/10/2026). Hết trận (rời
  ra menu, thoát game, đồng hồ game đứng 3 phút) tự chốt file. **Không tự dựng video** (từ 09/10/2026).
- Thẻ **Trận đã ghi** (mặc định) là bảng các trận: bấm đúp một trận hoặc **▶ Xem replay** để xem lại như replay LMHT
  (mục bên dưới). **Xuất video...** dựng file mp4 cho trận đang chọn khi bạn cần chia sẻ (chọn độ rộng 1920/2560/3840/9216,
  FPS, tua nhanh, sương mù...).
- Thẻ **Cài đặt**: nhịp đọc game, thư mục lưu, ảnh tĩnh theo mốc phút (mặc định tắt), và tuỳ chọn "Tự xuất video sau
  mỗi trận" (mặc định tắt). Thẻ **Nhật ký**: log. Cấu hình lưu ở `Video\_settings.ini`, nhật ký ở `Video\_mapcap.log`.
- Dòng lệnh dựng video: `AoE-MapCap.exe --render-raw file.aoerec [out.mp4] --width=3840 --fps=25`.

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

Xem video có phóng to: dùng **[mpv-for-aoe](https://github.com/trandinhnamuet/mpv-for-aoe)**
([tải bản Windows](https://github.com/trandinhnamuet/mpv-for-aoe/releases/latest/download/mpv-for-aoe-win64.zip)),
bản mpv mã nguồn mở chỉnh sẵn cho video này: lăn chuột zoom quanh con trỏ, kéo chuột trái để di chuyển, bấm chuột
giữa để về toàn bản đồ, zoom quá 1:1 vẫn giữ nét pixel; phát mượt cả video 9216 px. Trình phát khác: PotPlayer
(Ctrl + lăn chuột), VLC (Tools > Effects and Filters > Video Effects > Geometry > Interactive Zoom). Muốn chi tiết
hơn khi phóng, tăng độ rộng video lên 3840 hoặc 9216 (kích cỡ gốc).

### Xem replay (như replay Liên Minh Huyền Thoại)

Nút **Xem replay...** hiện bảng các trận đã ghi (ngày đánh, người chơi, quân, kết quả, thể thức "2v1 Random" /
"4v4 Shang", map "Hill Country - Large", thời lượng); chọn trận rồi bấm Delete để xoá (vào Thùng rác), nút "Nén trận
cũ" thu nhỏ file ghi bằng bản cũ 5-10 lần mà không mất dữ liệu; bấm đúp một trận để mở trong cửa sổ riêng, vẽ trực tiếp từ dữ liệu trận bằng OpenGL
(không cần dựng video): tua tới/lui bất kì lúc nào, đổi tầm nhìn từng đội, bảng tỉ số, zoom nét tới từng pixel game.
Từ 09/10/2026 file ghi thêm thiết lập ván (kiểu/cỡ bản đồ, đội, tài nguyên...) và kết quả thắng/thua; file cũ hiện
kết quả "Không rõ". Đội có người **đầu tiên** đầu hàng hoặc rớt mạng tính là đội thua (đội kia thắng, nếu trận có 2 đội),
kể cả khi dừng ghi trước lúc game tự kết luận ván.
Mở trận bất kì (kể cả file người khác gửi): nút **Mở file khác...** hoặc
`AoE-MapCap.exe --replay file.aoerec`. Cần thư mục game AoE-HD hoặc AOE1R trên máy để lấy đồ hoạ (trận của bản
này xem được bằng dữ liệu của bản kia: hình giống hệt).

| Phím | Việc |
|---|---|
| P | phát / tạm dừng |
| `-` / `=` / `0` | chậm / nhanh (0,25x … 16x) / về 1x |
| Backspace / J | lùi / tiến 15 giây |
| F1 / F2 / F3 | tầm nhìn đội 1 / đội 2 / toàn bản đồ; V xoay vòng, F bật-tắt sương mù |
| 1–5 / Q–T | chọn người chơi đội 1 / đội 2 (máy quay bay tới nhà chính); Space quay lại người đang chọn |
| O / X | bảng tỉ số / đổi cột kinh tế ↔ quân sự |
| C / U / H / M | bảng công nghệ / thanh thời gian / ẩn HUD / minimap |
| Lăn chuột | zoom quanh con trỏ; Home hoặc chuột giữa: cả bản đồ |
| Chuột ra mép, mũi tên, kéo chuột | di chuyển máy quay |
| Bấm vào unit / L | xem thông tin và khoá máy quay theo unit / bật-tắt khoá |
| S | bật/tắt âm thanh (tiếng của game theo những gì máy quay đang nhìn, tối đa x2) |
| F11 hoặc Alt+Enter | bật/tắt toàn màn hình |
| Esc hoặc ? | bảng phím tắt (hoặc bấm nút "Phím tắt (Esc)" trên thanh thời gian) |

Replay mở theo góc nhìn đội của người ghi (F3 để xem toàn bản đồ). Bấm vào unit (cả cây, mỏ) để xem bảng thông tin
như trong game: chân dung, tên, chủ, thanh máu còn/mất, công, giáp, giáp xuyên, tầm, tốc đánh, tốc chạy, tầm nhìn
(dạng "3+2" = gốc + nâng cấp; công/giáp chỉ có ở trận ghi từ 09/10/2026). Bấm vào nhà để xem bảng quân và nâng
cấp như người chơi thấy (nâng xong thì biến mất, bậc sau hiện ở cùng ô; rê chuột xem tên + giá). Bấm thanh thời gian hoặc minimap để nhảy tới. Chi tiết: `docs/10-trinh-xem-replay.md`.

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
- `replay/`: trình xem replay (pygame + moderngl); `run_replay.py` / `build_replay.py` chỉ để chạy thử và kiểm thử
  (từ v6 bản phát hành chỉ có AoE-MapCap.exe).
- `probe.py`: kiểm chứng offset khi đang trong game.
- `re/`: script dịch ngược tĩnh đã dùng để tìm offset (capstone).

## Lưu ý

- meme.dll của AoE-HD / AOE1R là anti-hack. Tool chỉ mở handle đọc, không sửa gì, nhưng
  không thể bảo đảm tuyệt đối anti-hack không phản ứng. Nên thử ở ván chơi đơn trước.
- Offset áp dụng cho EMPIRESX.EXE, EMPIRESX_HD.EXE, EMPIRESX_HDR.EXE, empires.exe
  và 4 file patch\EMPIRESX1..4.EXE của bản AoE-HD 0.5, Empiresx.exe / Empiresx_n.exe / Empiresx_r.exe của AOE1R
  (XArena). AOE1R chính là cùng chương trình, chỉ khác độ phân giải. Exe khác hẳn (vd Empires.exe = AoE gốc không
  có Rise of Rome) thì tool báo trong nhật ký và không ghi.
