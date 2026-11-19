# AoE-MapCap

**[⬇ Tải bản Windows mới nhất (AoE-MapCap-win64.zip)](https://github.com/trandinhnamuet/AoEMapCap/releases/latest/download/AoE-MapCap-win64.zip)**
· [Các phiên bản và có gì mới](https://github.com/trandinhnamuet/AoEMapCap/releases)
· [Kiểm tra file tải về](#kiểm-tra-file-tải-về)

Ghi lại trận **AoE-HD** và **AOE1R** (Age of Empires: Rise of Rome 1.0) rồi **xem lại như replay Liên Minh Huyền Thoại**:
tua tới / lui, đổi tầm nhìn từng đội hoặc từng người, máy quay tự động, bảng tỉ số, công nghệ, bấm vào unit xem máu / công /
giáp, zoom nét tới từng pixel game. Trong lúc ghi, app **tự phát hiện hack** và cho bạn **báo cáo** trận có hack.

Giải nén zip là chạy, không cần cài đặt. Tool chạy **song song, bên ngoài game**, chỉ **đọc** bộ nhớ tiến trình game
(ReadProcessMemory): không ghi bộ nhớ, không nạp DLL vào game. Cần thư mục game AoE-HD hoặc AOE1R trên máy để lấy đồ hoạ.

## Dùng nhanh

1. Mở `AoE-MapCap.exe` (hộp UAC hiện một lần: game chạy quyền Administrator nên tool cũng phải vậy mới đọc được).
2. Cứ vào game như thường. App luôn ghi khi đang mở; mỗi trận lưu thành một file `Video\Raw\*.aoerec` (khoảng 10-60 MB).
   Hết trận (rời ra menu, thoát game) app tự chốt file.
3. Thẻ **Trận đã ghi** liệt kê các trận (ngày, người chơi, quân, kết quả, thể thức, bản đồ, giờ kích đời 3, thời lượng).
   Bấm đúp một trận hoặc **▶ Xem replay** để xem lại.

Điều cần biết:

- Bấm X thì app thu xuống **khay hệ thống** và vẫn ghi trận. Ô **Khởi động cùng Windows** ở thanh bên (mặc định bật) để khỏi
  quên mở app.
- Đang ghi trận thì không tắt ghi, không thoát app được: để không ai dừng ghi giữa trận rồi xem bản đồ đối thủ.
- **★ Ghim** giữ trận đang chọn mãi mãi. Ô **Tự dọn trận cũ** ở thanh bên xoá các trận cũ nhất khi thư mục trận quá lớn,
  không bao giờ xoá trận ghim.
- Chuột phải vào một dòng trong bảng để mở rộng: hai đội, từng người chơi và quân.
- Mở trận người khác gửi: **bấm đúp file `.aoerec`** (app tự đăng ký loại file này cho tài khoản Windows của bạn; tắt ở
  **Cài đặt**), kéo thả file vào `AoE-MapCap.exe`, hoặc nút **Mở file khác...** trong app. Mỗi lần bấm đúp Windows hỏi quyền
  Administrator. Nếu bạn từng chọn "Open with" cho file `.aoerec` thì chọn lại AoE-MapCap một lần (Open with → Always).

Các thẻ ở thanh bên: **Trận đã ghi**, **Điện thoại**, **Cài đặt**, **Phím tắt**, **Nhật ký**, **Lịch sử báo cáo**,
**Góp ý / Báo lỗi**.

## Xem replay

Replay vẽ trực tiếp từ dữ liệu trận (không qua video) nên tua tới / lui tức thì và zoom vẫn nét. Replay mở theo góc nhìn
đội của người ghi.

- **Tầm nhìn:** các thẻ ở góc phải trên. Bấm thẻ một người chơi, hoặc bấm tên người đó ở bảng chỉ số bên dưới, để xem đúng
  những gì người đó thấy; máy quay bay tới nhà chính của họ và **máy quay tự động** bật lên. Bấm lại người đang xem để về
  tầm nhìn cả đội. Thẻ **Toàn bản đồ** (F3) xem tất cả.
- **Máy quay tự động (A):** tự theo giao tranh, rồi công trình đang xây, rồi dân làm việc. Tự kéo máy quay thì nó tắt.
- **Bấm vào unit / công trình:** bảng thông tin như trong game (máu, công, giáp, tầm, tốc độ; "3+2" = gốc + nâng cấp). Bấm
  vào nhà để xem bảng quân và nâng cấp như người chơi thấy, cùng hàng đợi sinh quân.
- **Bảng công nghệ** (góc trái trên) cho từng người trong tầm nhìn đang xem; **bảng chỉ số** bên dưới có kinh tế / quân sự.
- Nút **⚙ Cài đặt** trên thanh thời gian: máy quay tự động, tầm nhìn, tốc độ, âm thanh.

| Phím | Việc |
|---|---|
| P | phát / tạm dừng |
| `-` / `=` / `0` | chậm / nhanh (0,25x … 16x) / về 1x |
| Backspace / J | lùi / tiến 15 giây |
| F1 / F2 / F3 | tầm nhìn đội 1 / đội 2 / toàn bản đồ; V xoay vòng, F bật-tắt sương mù |
| 1–5 / Q–T | chọn người chơi đội 1 / đội 2; Space quay lại người đang chọn |
| A | máy quay tự động |
| O / X | bảng tỉ số / đổi cột kinh tế ↔ quân sự |
| C / U / H / M | bảng công nghệ / thanh thời gian / ẩn HUD / minimap |
| Lăn chuột | zoom quanh con trỏ; Home hoặc chuột giữa: cả bản đồ |
| Chuột ra mép, mũi tên, kéo chuột | di chuyển máy quay |
| Bấm vào unit / L | xem thông tin và khoá máy quay theo unit / bật-tắt khoá |
| Chuột phải kéo | khoanh vùng hiện thanh máu |
| S | bật / tắt âm thanh (tiếng của game theo những gì máy quay đang nhìn, tối đa x2) |
| F11 hoặc Alt+Enter | bật / tắt toàn màn hình |
| Esc hoặc ? | bảng phím tắt |

## Phát hiện hack

### Cách hoạt động

Game AoE chơi mạng theo kiểu mọi máy cùng mô phỏng: lệnh của **mọi** người chơi đều đi qua máy bạn. Trong trận, AoE-MapCap
đọc các lệnh đó cùng tài nguyên, công nghệ, quân của từng người (chỉ đọc, như phần ghi trận) và so với bộ luật dưới đây.
Mọi thứ app kết luận đều dựa trên dữ liệu có trong file trận, nên xem lại và kiểm chứng được.

Phát hiện thì: chuông cảnh báo (ô **Báo âm thanh khi có hack** ở thanh bên), thẻ đỏ ở góc phải trên cửa sổ app, và trận đó
hiện **⚠** trong Trận đã ghi kèm tên người hack, loại hack, phút xảy ra. Chi tiết ghi rõ unit theo tên thường gọi, ví dụ
"di chuyển ngựa dò #17299 của P5 (tên người chơi)".

### Các luật

| Mã | Phát hiện | Giải thích |
|---|---|---|
| L1 | Điều khiển / xoá thú, vật thể Gaia | Ra lệnh hoặc xoá thú rừng, cây, mỏ (lùa voi, linh dương về nhà; xoá để lấy thịt ngay) |
| L2 | Điều khiển quân / nhà của người khác | Ra lệnh cho quân hoặc nhà của người chơi khác, kể cả đồng minh |
| L3 | Xoá quân / nhà của người khác | Gửi lệnh xoá thứ không phải của mình |
| L5 | Dùng lệnh cheat khi phòng không bật cheat | Tạo unit, tự cộng tài nguyên (kể cả cộng từng ít một), xây tức thì |
| L7 | Ra quân / nâng cấp thứ chưa mở | Chưa đủ đời, thiếu nhà, hoặc văn minh không có |
| S1 | Tài nguyên vượt 1.000.000 | |
| S2 | Tài nguyên tăng đột biến | Tăng từ 1.000 trở lên trong 1 giây mà không phải được cống nạp hay được hoàn tiền |
| S3 | Có unit chỉ cheat mới có | Lính hạt nhân, Photon Man, Medusa... |
| M1 | Nghi hack map sáng | Ra lệnh thẳng vào quân, nhà đối phương hoặc bụi quả, mỏ, thú ở vùng mình và đồng đội **chưa từng khám phá** |
| L4 | Ép người khác đầu hàng | **Tắt sẵn**: từng báo oan khi đối thủ thoát hoặc rớt mạng |

Bật / tắt từng luật ở **Cài đặt → Phát hiện hack** (áp dụng từ trận ghi kế tiếp).

Ngoài ra có một mức **ghi nhận**, không phải kết luận hack: "Có dấu hiệu cài tool hack". Đó là khi một người gửi lệnh của
tool hack nhưng chưa cộng gì. Mức này không báo động, chỉ lưu vào file trận và gửi kèm khi bạn báo cáo.

### Những gì app cố ý không báo

- **Đánh với máy:** app chỉ kết luận khi có từ hai người thật trở lên (người thật là người tự gửi lệnh; lệnh của máy do máy
  chủ phòng gửi thay).
- **Quân vừa bị thầy tu phù:** lệnh của chủ cũ trong vài giây đầu không tính.
- **Hoàn tiền:** huỷ nghiên cứu, huỷ hàng đợi sinh quân, mất công trình, hết ván.
- **Bấm sớm:** bấm nút lên đời / nâng cấp ngay trước khi đủ điều kiện mà game bỏ qua lệnh đó.
- **Phòng bật cheat:** các luật L5, S1, S2, S3 không áp dụng.

### Giới hạn

- Hack chỉ chạy trên máy người hack mà **không gửi lệnh nào** thì app không thấy. Riêng hack map sáng chỉ bắt được khi
  người đó ra lệnh thẳng vào thứ họ không thể thấy.
- Cảnh báo trong trận có thể hiện trễ vài giây; giờ ghi trong báo cáo vẫn là giờ xảy ra.
- App có thể báo oan hoặc bỏ sót. Thấy vậy hãy báo cáo (mục dưới) để bổ sung luật.

## Báo cáo hack và phản hồi của admin

Thấy trận có hack, **hoặc app báo oan**: bấm **⚑ Báo cáo hack**, chọn trận (trận app đã bắt được có ⚠), chọn người bị
nghi, ghi chú hack gì và phút mấy, rồi gửi. File trận được gửi lên máy chủ của AoE-MapCap để admin xem lại và bổ sung luật.

Thẻ **Lịch sử báo cáo** liệt kê các trận bạn đã báo cáo từ máy này, mở lại replay được, và có khung **tin nhắn với admin**:

- Admin kết luận (Có hack / Không hack) hoặc nhắn lại thì mục **Lịch sử báo cáo** ở thanh bên hiện **huy hiệu đỏ** với số
  phản hồi chưa đọc. Mở báo cáo đó ra xem là hết.
- Bạn trả lời admin ngay trong khung đó.

## Thông báo từ admin

Thỉnh thoảng khi mở app bạn có thể thấy một hộp **THÔNG BÁO** giữa cửa sổ (ví dụ lịch bảo trì, hướng dẫn cho bản mới).
Bấm **Đã hiểu** thì thông báo đó không hiện lại. Thông báo đi kèm lượt "mở app" gửi tới máy chủ thống kê, app không mở
thêm kết nối nào khác.

## Xem trận trên điện thoại

App Android **AoE-MapCap** (repo riêng: [AoEMapCap-Mobile](https://github.com/trandinhnamuet/AoEMapCap-Mobile),
[tải APK mới nhất](https://github.com/trandinhnamuet/AoEMapCap-Mobile/releases/latest/download/AoE-MapCap.apk)) xem lại
trận đã ghi như trình xem trên máy tính. Trên máy tính vào thẻ **Điện thoại**, bật "Cho điện thoại xem trận" rồi quét mã
QR bằng app (hoặc bằng camera để xem trên trình duyệt). Điện thoại dùng mạng nào cũng được. Máy tính chỉ gửi file ghi
trận, điện thoại tự dựng và phát ngay; trận đã mở được lưu trên điện thoại.

## Cập nhật

Mỗi khi mở (và 6 giờ một lần) app tự xem có bản mới chưa. Có bản mới thì hiện thanh **Có bản mới vN**: **Có gì mới** xem
thay đổi, **Cập nhật** để app tự tải, kiểm mã SHA-256, thay file rồi mở lại. Đang ghi trận thì app chờ xong mới cập nhật.
Không có mạng vẫn dùng bình thường. Mỗi bản có gì mới:
[trang Releases](https://github.com/trandinhnamuet/AoEMapCap/releases).

## Dữ liệu app gửi đi

Lần mở đầu tiên app hiện thông báo về các mục dưới đây (kèm ô tích Khởi động cùng Windows) trước khi gửi gì đi.

- **Thống kê sử dụng:** mỗi lần mở app và mỗi trận ghi xong, app gửi một lượt lên Cloudflare: **mã máy ngẫu nhiên** (lưu ở
  `%APPDATA%\AoE-MapCap\install_id`), **tên người chơi** (nickname của người ghi), phiên bản; máy nhận ghi thêm địa chỉ
  IP. Không gửi nội dung trận. Tắt trong thẻ **Cài đặt** (bỏ ô "Gửi thống kê sử dụng").
- **Báo cáo hack:** chỉ khi bạn bấm gửi: file trận, mã máy, phiên bản, tên trong game của bạn, người bị nghi và ghi chú.
- **Điện thoại:** file trận đi qua trạm chuyển tiếp chỉ khi bạn bật "Cho điện thoại xem trận".

## Kiểm tra file tải về

Mã băm SHA-256 nằm trong `SHA256SUMS.txt` (trong zip) và `AoE-MapCap-win64.zip.sha256` (trên trang Release). App tự kiểm
mã này khi cập nhật. Exe chưa được ký số nên Windows SmartScreen hoặc phần mềm diệt virus có thể cảnh báo nhầm; chỉ tải
từ trang Releases của repo này.

## Lưu ý

- `meme.dll` của AoE-HD / AOE1R là anti-hack. Tool chỉ mở handle đọc, không sửa gì, nhưng không thể bảo đảm tuyệt đối
  anti-hack không phản ứng.
- Hỗ trợ EMPIRESX.EXE, EMPIRESX_HD.EXE, EMPIRESX_HDR.EXE, empires.exe của AoE-HD và Empiresx.exe / Empiresx_n.exe /
  Empiresx_r.exe của AOE1R (XArena); các sảnh khác dùng cùng bản game cũng ghi được. Exe khác hẳn (ví dụ AoE gốc không có
  Rise of Rome) thì app báo trong Nhật ký và không ghi.
- Cấu hình lưu ở `Video\_settings.ini`, nhật ký ở `Video\_mapcap.log`, danh sách ghim ở `Video\Raw\_keep.json`, lịch sử
  báo cáo ở `Video\_report_history.json`.

## Giấy phép

Phần mềm phát hành dạng chương trình (file thực thi), miễn phí cho cá nhân sử dụng. Giữ toàn bộ bản quyền, xem
[LICENSE](LICENSE). Repo này chỉ chứa bản phát hành, không chứa mã nguồn.
