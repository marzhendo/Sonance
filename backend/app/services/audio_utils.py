"""Utilitas pemrosesan audio untuk validasi format dan ekstraksi durasi Opus."""
import struct
from fastapi import HTTPException, status


def validate_opus_format(data: bytes) -> None:
    """
    Validasi bahwa data audio memiliki header container Ogg dan payload Opus.
    Raises HTTPException 400 jika format bukan Opus.
    """
    if len(data) < 36 or not data.startswith(b"OggS"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format file tidak valid. Hanya file berformat Opus yang diterima.",
        )
    # Header page pertama Ogg Opus wajib memuat identifier OpusHead
    if b"OpusHead" not in data[:100]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format file tidak valid. Hanya file berformat Opus yang diterima.",
        )


def extract_opus_duration(data: bytes) -> float:
    """
    Mengekstrak durasi file Ogg Opus dalam detik berdasarkan granule position.
    Opus selalu menggunakan base sample rate 48000 Hz untuk kalkulasi granule.
    Validasi memastikan keutuhan setiap page dan adanya penanda end-of-stream (EOS).
    """
    validate_opus_format(data)

    last_granule = None
    has_eos = False
    offset = 0
    data_len = len(data)

    try:
        while offset < data_len:
            page_start = data.find(b"OggS", offset)
            if page_start == -1:
                break
            if page_start + 27 > data_len:
                raise ValueError("Header OggS terpotong.")

            flags = data[page_start + 5]

            # Ekstrak granule position (int64 little-endian pada offset 6..14)
            granule = struct.unpack("<q", data[page_start + 6:page_start + 14])[0]

            # Hitung panjang page dari segment table
            num_segments = data[page_start + 26]
            seg_table_start = page_start + 27
            seg_table_end = seg_table_start + num_segments
            if seg_table_end > data_len:
                raise ValueError("Tabel segmen Ogg terpotong.")

            body_len = sum(data[seg_table_start:seg_table_end])
            page_end = seg_table_end + body_len
            if page_end > data_len:
                raise ValueError("Body page Ogg terpotong.")

            if granule > 0:
                last_granule = granule

            if flags & 0x04:
                has_eos = True

            offset = page_end
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File audio corrupt atau tidak dapat diproses.",
        ) from e

    if not has_eos or last_granule is None or last_granule <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File audio corrupt atau tidak dapat diproses.",
        )

    duration = last_granule / 48000.0
    return round(duration, 3)


def validate_and_extract_duration(data: bytes) -> float:
    """
    Validasi format Opus dan rentang durasi 10 hingga 30 detik.
    """
    duration = extract_opus_duration(data)
    if duration < 10.0 or duration > 30.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Durasi audio harus berada di antara 10 hingga 30 detik.",
        )
    return duration

