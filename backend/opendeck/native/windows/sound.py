"""Sound effects: decode an audio file with Media Foundation, play it with waveOut.

- Decoding: the Media Foundation Source Reader turns MP3, WAV, AAC/M4A, WMA, FLAC and
  (with Windows' Web Media Extensions, preinstalled on Windows 10/11) OGG/Opus into
  16-bit PCM. The same codecs Windows' own players use; nothing is bundled.
- Playback: waveOut on a chosen output device. Core Audio endpoint ids (what the editor
  lists) map to waveOut device numbers through DRV_QUERYFUNCTIONINSTANCEID.
  Windows mixes several sounds at once, so effects can overlap.

Functions run on any worker thread; each one initialises COM for itself.
"""

from __future__ import annotations

import array
import ctypes
import os
import struct
import tempfile
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from . import com
from .session import PlatformError, _require_windows

MF_VERSION = 0x00020070
FIRST_AUDIO_STREAM = 0xFFFFFFFD
ALL_STREAMS = 0xFFFFFFFE
READERF_ENDOFSTREAM = 0x2

MF_MT_MAJOR_TYPE = "48eba18e-f8c9-4687-bf11-0a74c9f96a8f"
MF_MT_SUBTYPE = "f7e34c9a-42e8-4714-b74b-cb29d72c35e5"
MF_MT_AUDIO_NUM_CHANNELS = "37e48bf5-645e-4c5b-89de-ada9e29b696a"
MF_MT_AUDIO_SAMPLES_PER_SECOND = "5faeeae7-0290-4c31-9e8a-c534f68d9dba"
MF_MT_AUDIO_BITS_PER_SAMPLE = "f2deb57f-40fa-4764-aa33-ed4f2d1ff669"
MFMediaType_Audio = "73647561-0000-0010-8000-00aa00389b71"
MFAudioFormat_PCM = "00000001-0000-0010-8000-00aa00389b71"

# IMFAttributes / IMFSample / IMFMediaBuffer / IMFSourceReader vtable slots.
_GET_UINT32, _SET_UINT32, _SET_GUID = 7, 21, 24
_CONVERT_TO_CONTIGUOUS = 41
_LOCK, _UNLOCK = 3, 4
_SET_STREAM_SELECTION, _GET_CURRENT_TYPE, _SET_CURRENT_TYPE, _READ_SAMPLE = 4, 6, 7, 9

WAVE_MAPPER = 0xFFFFFFFF
WAVE_FORMAT_PCM = 1
WHDR_DONE = 0x1
DRV_QUERYFUNCTIONINSTANCEID = 0x0811
DRV_QUERYFUNCTIONINSTANCEIDSIZE = 0x0812

# A sound effect, not an album: decoded PCM above this is refused (about 9 min of 48 kHz stereo).
MAX_PCM_BYTES = 100 * 1024 * 1024


class SoundError(PlatformError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Pcm:
    data: bytes  # interleaved signed 16-bit little-endian
    channels: int
    rate: int

    @property
    def seconds(self) -> float:
        return len(self.data) / (self.channels * 2 * self.rate)


# ---- decoding ------------------------------------------------------------------------------

_mf_lock = threading.Lock()
_mf: tuple | None = None


def _mf_api():
    global _mf
    with _mf_lock:
        if _mf is None:
            _require_windows()
            mfplat = ctypes.WinDLL("mfplat")
            reader = ctypes.WinDLL("mfreadwrite")
            mfplat.MFStartup.argtypes = [wintypes.ULONG, wintypes.DWORD]
            mfplat.MFStartup.restype = ctypes.c_long
            mfplat.MFCreateMediaType.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
            mfplat.MFCreateMediaType.restype = ctypes.c_long
            reader.MFCreateSourceReaderFromURL.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                                           ctypes.POINTER(ctypes.c_void_p)]
            reader.MFCreateSourceReaderFromURL.restype = ctypes.c_long
            com.check(mfplat.MFStartup(MF_VERSION, 0), "MFStartup")  # never shut down: process-wide
            _mf = (mfplat, reader)
        return _mf


def _guid(text: str):
    return ctypes.byref(com.GUID.parse(text))


def decode(path: str) -> Pcm:
    """Whole file as 16-bit PCM. Raises SoundError for unreadable or unsupported files.

    Windows registers no Ogg reader for desktop apps, but decodes Vorbis and Opus inside
    WebM; so .ogg/.opus files are rewrapped (not re-encoded) into WebM first.
    """
    if path.lower().endswith((".ogg", ".oga", ".opus")):
        try:
            with open(path, "rb") as f:
                webm = ogg_to_webm(f.read())
        except OSError as exc:
            raise SoundError("FILE_NOT_FOUND", "The sound file could not be read.") from exc
        fd, temp = tempfile.mkstemp(suffix=".webm")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(webm)
            return _decode(temp)
        finally:
            os.unlink(temp)
    return _decode(path)


def _decode(path: str) -> Pcm:
    com.init_thread()
    mfplat, reader_dll = _mf_api()
    raw = ctypes.c_void_p()
    if reader_dll.MFCreateSourceReaderFromURL(path, None, ctypes.byref(raw)) < 0:
        raise SoundError("UNSUPPORTED_AUDIO", "Windows can't open this audio file. Try MP3 or WAV.")
    with com.ComPtr(raw) as reader:
        reader.hr(_SET_STREAM_SELECTION, "SetStreamSelection", [wintypes.DWORD, wintypes.BOOL], ALL_STREAMS, False)
        try:
            reader.hr(_SET_STREAM_SELECTION, "SetStreamSelection", [wintypes.DWORD, wintypes.BOOL],
                      FIRST_AUDIO_STREAM, True)
        except com.ComError as exc:
            raise SoundError("NO_AUDIO", "This file has no sound in it.") from exc

        wanted = ctypes.c_void_p()
        com.check(mfplat.MFCreateMediaType(ctypes.byref(wanted)), "MFCreateMediaType")
        with com.ComPtr(wanted) as media_type:
            guid_args = [ctypes.POINTER(com.GUID), ctypes.POINTER(com.GUID)]
            media_type.hr(_SET_GUID, "SetGUID", guid_args, _guid(MF_MT_MAJOR_TYPE), _guid(MFMediaType_Audio))
            media_type.hr(_SET_GUID, "SetGUID", guid_args, _guid(MF_MT_SUBTYPE), _guid(MFAudioFormat_PCM))
            media_type.hr(_SET_UINT32, "SetUINT32", [ctypes.POINTER(com.GUID), ctypes.c_uint32],
                          _guid(MF_MT_AUDIO_BITS_PER_SAMPLE), 16)
            try:
                reader.hr(_SET_CURRENT_TYPE, "SetCurrentMediaType",
                          [wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p], FIRST_AUDIO_STREAM, None, media_type.ptr)
            except com.ComError as exc:
                raise SoundError("UNSUPPORTED_AUDIO",
                                 "Windows has no decoder for this audio format. Try MP3 or WAV.") from exc

        with reader.out_ptr(_GET_CURRENT_TYPE, "GetCurrentMediaType", [wintypes.DWORD], FIRST_AUDIO_STREAM) as actual:
            def uint32(key: str) -> int:
                value = ctypes.c_uint32()
                actual.hr(_GET_UINT32, "GetUINT32", [ctypes.POINTER(com.GUID), ctypes.POINTER(ctypes.c_uint32)],
                          _guid(key), ctypes.byref(value))
                return value.value

            channels, rate, bits = uint32(MF_MT_AUDIO_NUM_CHANNELS), uint32(MF_MT_AUDIO_SAMPLES_PER_SECOND), \
                uint32(MF_MT_AUDIO_BITS_PER_SAMPLE)
        if bits != 16 or not channels or not rate:
            raise SoundError("UNSUPPORTED_AUDIO", "Windows can't convert this audio file. Try MP3 or WAV.")

        chunks: list[bytes] = []
        total = 0
        while True:
            flags, sample = wintypes.DWORD(), ctypes.c_void_p()
            reader.hr(_READ_SAMPLE, "ReadSample",
                      [wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                       ctypes.POINTER(ctypes.c_longlong), ctypes.POINTER(ctypes.c_void_p)],
                      FIRST_AUDIO_STREAM, 0, None, ctypes.byref(flags), None, ctypes.byref(sample))
            if sample:
                with com.ComPtr(sample) as s, s.out_ptr(_CONVERT_TO_CONTIGUOUS, "ConvertToContiguousBuffer", []) as buf:
                    data, length = ctypes.c_void_p(), wintypes.DWORD()
                    buf.hr(_LOCK, "Lock", [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                           ctypes.POINTER(wintypes.DWORD)], ctypes.byref(data), None, ctypes.byref(length))
                    try:
                        chunks.append(ctypes.string_at(data, length.value))
                    finally:
                        buf.hr(_UNLOCK, "Unlock", [])
                total += len(chunks[-1])
                if total > MAX_PCM_BYTES:
                    raise SoundError("AUDIO_TOO_LONG", "This file is too long for a sound effect (about 9 minutes max).")
            if flags.value & READERF_ENDOFSTREAM:
                break
    if not total:
        raise SoundError("NO_AUDIO", "This file has no sound in it.")
    return Pcm(b"".join(chunks), channels, rate)


def _ogg_packets(data: bytes) -> list[tuple[bytes, int]]:
    """(packet, granule position of the page before it) for the first logical stream of an Ogg file."""
    packets: list[tuple[bytes, int]] = []
    partial = b""
    serial = None
    page_start = 0  # granule at the end of the previous page = time the page's packets start
    pos = 0
    while pos + 27 <= len(data):
        if data[pos:pos + 4] != b"OggS":
            raise SoundError("UNSUPPORTED_AUDIO", "This OGG file is damaged.")
        granule, page_serial = struct.unpack_from("<qI", data, pos + 6)
        count = data[pos + 26]
        lacing = data[pos + 27:pos + 27 + count]
        body = pos + 27 + count
        pos = body + sum(lacing)
        if serial is None:
            serial = page_serial
        if page_serial != serial:
            continue  # another stream multiplexed in (rare for audio files)
        offset = body
        for size in lacing:
            partial += data[offset:offset + size]
            offset += size
            if size < 255:
                packets.append((partial, page_start))
                partial = b""
        if granule >= 0:
            page_start = granule
    return packets


def _ebml(element_id: int, payload: bytes) -> bytes:
    size = len(payload)
    return element_id.to_bytes((element_id.bit_length() + 7) // 8, "big") + (0x01 << 56 | size).to_bytes(8, "big") + payload


def _uint(element_id: int, value: int) -> bytes:
    return _ebml(element_id, value.to_bytes(8, "big"))


def ogg_to_webm(data: bytes) -> bytes:
    """Rewrap an Ogg Vorbis or Ogg Opus file as WebM, packet for packet."""
    packets = _ogg_packets(data)
    if not packets:
        raise SoundError("UNSUPPORTED_AUDIO", "This OGG file is damaged.")
    first = packets[0][0]
    if first.startswith(b"\x01vorbis") and len(packets) > 3:
        headers, audio = [p for p, _ in packets[:3]], packets[3:]
        channels, rate = first[11], struct.unpack_from("<I", first, 12)[0]
        lacing = b"".join(b"\xff" * (len(h) // 255) + bytes([len(h) % 255]) for h in headers[:2])
        codec = _ebml(0x86, b"A_VORBIS") + _ebml(0x63A2, b"\x02" + lacing + b"".join(headers))
    elif first.startswith(b"OpusHead") and len(packets) > 2:
        audio = packets[2:]  # after OpusHead and OpusTags
        channels, rate = first[9], 48000
        pre_skip = struct.unpack_from("<H", first, 10)[0]
        codec = (_ebml(0x86, b"A_OPUS") + _ebml(0x63A2, first)
                 + _uint(0x56AA, pre_skip * 1_000_000_000 // 48000) + _uint(0x56BB, 80_000_000))
    else:
        raise SoundError("UNSUPPORTED_AUDIO", "Only OGG files with Vorbis or Opus sound are supported.")

    track = _ebml(0xAE, _uint(0xD7, 1) + _uint(0x73C5, 1) + _uint(0x83, 2) + codec
                  + _ebml(0xE1, _ebml(0xB5, struct.pack(">d", float(rate))) + _uint(0x9F, channels)))
    clusters = []
    cluster_ms, blocks = 0, []
    for packet, granule in audio:
        ms = granule * 1000 // rate
        if ms - cluster_ms > 30_000:  # block times are 16-bit offsets from their cluster
            clusters.append(_ebml(0x1F43B675, _uint(0xE7, cluster_ms) + b"".join(blocks)))
            cluster_ms, blocks = ms, []
        blocks.append(_ebml(0xA3, b"\x81" + struct.pack(">hB", ms - cluster_ms, 0x80) + packet))
    clusters.append(_ebml(0x1F43B675, _uint(0xE7, cluster_ms) + b"".join(blocks)))
    header = _ebml(0x1A45DFA3, _uint(0x4286, 1) + _uint(0x42F7, 1) + _uint(0x42F2, 4) + _uint(0x42F3, 8)
                   + _ebml(0x4282, b"webm") + _uint(0x4287, 4) + _uint(0x4285, 2))
    segment = _ebml(0x18538067, _ebml(0x1549A966, _uint(0x2AD7B1, 1_000_000)) + _ebml(0x1654AE6B, track)
                    + b"".join(clusters))
    return header + segment


def scaled(pcm: Pcm, percent: int) -> Pcm:
    """The same sound at `percent` volume (0-100)."""
    if percent >= 100:
        return pcm
    samples = array.array("h", pcm.data)
    factor = max(0, percent) / 100
    return Pcm(array.array("h", [int(s * factor) for s in samples]).tobytes(), pcm.channels, pcm.rate)


# ---- playback ------------------------------------------------------------------------------

class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD), ("nSamplesPerSec", wintypes.DWORD),
                ("nAvgBytesPerSec", wintypes.DWORD), ("nBlockAlign", wintypes.WORD),
                ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]


class WAVEHDR(ctypes.Structure):
    pass


WAVEHDR._fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                    ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_size_t), ("dwFlags", wintypes.DWORD),
                    ("dwLoops", wintypes.DWORD), ("lpNext", ctypes.POINTER(WAVEHDR)), ("reserved", ctypes.c_size_t)]

_winmm = None


def _wave():
    global _winmm
    if _winmm is None:
        _require_windows()
        w = ctypes.WinDLL("winmm")
        w.waveOutGetNumDevs.restype = wintypes.UINT
        w.waveOutMessage.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t]
        w.waveOutMessage.restype = wintypes.UINT
        w.waveOutOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), wintypes.UINT, ctypes.POINTER(WAVEFORMATEX),
                                  ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
        w.waveOutOpen.restype = wintypes.UINT
        for name in ("waveOutPrepareHeader", "waveOutWrite", "waveOutUnprepareHeader"):
            getattr(w, name).argtypes = [ctypes.c_void_p, ctypes.POINTER(WAVEHDR), wintypes.UINT]
            getattr(w, name).restype = wintypes.UINT
        for name in ("waveOutReset", "waveOutClose"):
            getattr(w, name).argtypes = [ctypes.c_void_p]
            getattr(w, name).restype = wintypes.UINT
        _winmm = w
    return _winmm


def endpoint_ids() -> list[str]:
    """Core Audio endpoint id of each waveOut device, by device number."""
    w = _wave()
    ids = []
    for index in range(w.waveOutGetNumDevs()):
        size = ctypes.c_size_t()
        text = ""
        if w.waveOutMessage(index, DRV_QUERYFUNCTIONINSTANCEIDSIZE, ctypes.addressof(size), 0) == 0 and size.value:
            buffer = ctypes.create_unicode_buffer(size.value // 2 + 1)
            if w.waveOutMessage(index, DRV_QUERYFUNCTIONINSTANCEID, ctypes.addressof(buffer), size.value) == 0:
                text = buffer.value
        ids.append(text)
    return ids


def _device_number(endpoint_id: str | None) -> int:
    if not endpoint_id:
        return WAVE_MAPPER  # follows the Windows default output
    try:
        return endpoint_ids().index(endpoint_id)
    except ValueError:
        raise SoundError("DEVICE_NOT_FOUND", "The selected audio device is not connected.") from None


class Playback:
    """One sound playing on one device. `wait()` returns when it ends or is stopped."""

    def __init__(self, pcm: Pcm, endpoint_id: str | None = None) -> None:
        w = _wave()
        fmt = WAVEFORMATEX(WAVE_FORMAT_PCM, pcm.channels, pcm.rate, pcm.rate * pcm.channels * 2, pcm.channels * 2, 16, 0)
        self._handle = ctypes.c_void_p()
        if w.waveOutOpen(ctypes.byref(self._handle), _device_number(endpoint_id), ctypes.byref(fmt), 0, 0, 0):
            raise SoundError("PLAYBACK_FAILED", "Windows could not play on that audio device.")
        self._buffer = ctypes.create_string_buffer(pcm.data, len(pcm.data))  # must outlive playback
        self._header = WAVEHDR(lpData=ctypes.cast(self._buffer, ctypes.c_void_p), dwBufferLength=len(pcm.data))
        self._closed = False
        self._lock = threading.Lock()
        if w.waveOutPrepareHeader(self._handle, ctypes.byref(self._header), ctypes.sizeof(WAVEHDR)) or \
                w.waveOutWrite(self._handle, ctypes.byref(self._header), ctypes.sizeof(WAVEHDR)):
            self._close()
            raise SoundError("PLAYBACK_FAILED", "Windows could not play this sound.")

    @property
    def done(self) -> bool:
        return self._closed or bool(self._header.dwFlags & WHDR_DONE)

    def wait(self) -> None:
        while not self.done:
            time.sleep(0.02)
        self._close()

    def stop(self) -> None:
        with self._lock:
            if not self._closed:
                _wave().waveOutReset(self._handle)  # marks the buffer done at once

    def _close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            w = _wave()
            w.waveOutReset(self._handle)
            w.waveOutUnprepareHeader(self._handle, ctypes.byref(self._header), ctypes.sizeof(WAVEHDR))
            w.waveOutClose(self._handle)
