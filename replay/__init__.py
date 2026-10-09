"""AoE-Replay: trình xem lại trận từ dữ liệu thô .aoerec của AoE-MapCap (tua, đổi tầm nhìn, zoom, HUD như LMHT).

Gói này chỉ phụ thuộc phần đọc dữ liệu/đồ hoạ của `mapcap` (rawrec, dat, drs, slp, render_full, video_render, lang),
không phụ thuộc phần ghi/đọc bộ nhớ game, nên tách thành phần mềm riêng được: điểm vào `run_replay.py`.

    data.py    mở file, lập chỉ mục, điểm mốc, trạng thái từng mẫu (không dính đồ hoạ)
    world.py   dựng ảnh địa hình + bản đồ chỉ số ô; danh sách sprite của unit (dùng lại logic của bộ vẽ video)
    gpu.py     OpenGL (moderngl): địa hình, sprite theo lô, sương mù theo pixel, minimap
    hud.py     HUD vẽ bằng pygame: thanh thời gian, bảng tỉ số, công nghệ, trợ giúp
    viewer.py  cửa sổ, vòng lặp, máy quay, phím tắt kiểu replay LMHT
"""
APP_NAME = "AoE-Replay"
