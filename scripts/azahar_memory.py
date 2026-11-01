"""Read-only Windows Azahar memory research. No debug listener or write access.

Host addresses are session-specific; never use them in an AMUN profile.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from pathlib import Path
import struct


class Region(C.Structure):
    _fields_ = [('base', C.c_void_p), ('allocation', C.c_void_p),
                ('allocation_protect', W.DWORD), ('partition', W.WORD),
                ('size', C.c_size_t), ('state', W.DWORD),
                ('protect', W.DWORD), ('kind', W.DWORD)]


class AzaharMemory:
    def __init__(self, pid: int):
        self.api = C.WinDLL('kernel32', use_last_error=True)
        self.api.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.api.OpenProcess.restype = W.HANDLE
        self.api.CloseHandle.argtypes = [W.HANDLE]
        self.api.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        self.api.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
        self.api.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.POINTER(Region), C.c_size_t]
        self.api.VirtualQueryEx.restype = C.c_size_t
        self.handle = self.api.OpenProcess(0x0400 | 0x0010, False, pid)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        name, size = C.create_unicode_buffer(32768), W.DWORD(32768)
        if not self.api.QueryFullProcessImageNameW(self.handle, 0, name, C.byref(size)):
            self.close()
            raise C.WinError(C.get_last_error())
        self.path = Path(name.value)
        expected = Path(__file__).resolve().parents[1] / 'build/emulators/azahar-2126.1.1/azahar-windows-msys2-2126.1.1/azahar.exe'
        if str(self.path).lower() != str(expected).lower():
            self.close()
            raise ValueError('Refusing a process other than the isolated research Azahar')

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def read(self, address: int, size: int) -> bytes:
        if not 0 < size <= 16 * 1024 * 1024 or address <= 0:
            raise ValueError('Read outside bounds')
        data, count = C.create_string_buffer(size), C.c_size_t()
        if not self.api.ReadProcessMemory(self.handle, address, data, size, C.byref(count)) or count.value != size:
            raise C.WinError(C.get_last_error())
        return data.raw

    def regions(self):
        address = 0
        while address < 0x7FFFFFFF0000:
            region = Region()
            if not self.api.VirtualQueryEx(self.handle, address, C.byref(region), C.sizeof(region)):
                break
            if region.state == 0x1000 and not region.protect & 0x100 and region.protect & 0xEE:
                yield region
            address = (region.base or 0) + region.size


class GuestMemory:
    """Translate pages through Azahar's raw page table, rejecting null mappings."""
    def __init__(self, host: AzaharMemory, table: int):
        self.host, self.table = host, table

    def read_memory(self, address: int, size: int) -> bytes:
        if not 0 < size <= 4096 or not 0 < address < address + size <= 0x100000000:
            raise ValueError('Guest read outside bounds')
        result = bytearray()
        while size:
            page = int.from_bytes(self.host.read(self.table + (address >> 12) * 8, 8), 'little')
            if not page:
                raise ValueError(f'Unmapped/cached guest page {address:#x}')
            count = min(size, 4096 - (address & 4095))
            result.extend(self.host.read(page + (address & 4095), count))
            address += count
            size -= count
        return bytes(result)

    def u32(self, address: int) -> int:
        return int.from_bytes(self.read_memory(address, 4), 'little')

    def validate(self):
        root = self.u32(0x006789C8)
        if not 0x14000000 <= root < 0x17800000:
            raise ValueError('Unsupported root scene')
        if self.read_memory(root + 0x20C, 1) != b'\x01':
            raise ValueError('System engine absent')
        system = self.u32(root + 0x208) ^ 0x75F1B26B
        manager = self.u32(system + 0x28)
        if self.read_memory(manager + 0xC0, 4) != b'SSDC':
            raise ValueError('Save header does not match expected layout')
        return manager

    @classmethod
    def discover(cls, host: AzaharMemory):
        candidates = set()
        # Azahar 2126.1.1 PageTable: 8 MiB raw pointers, MemoryRef array,
        # and attributes. Inspect only allocation prefixes, not whole RAM.
        for region in host.regions():
            if region.kind != 0x20000 or region.protect != 4 or not 0x3100000 <= region.size <= 0x3200000:
                continue
            values = struct.unpack('<3072Q', host.read(region.base, 0x6000))
            for i in range(0x100, len(values) - 4):
                if not 0x10000000000 < values[i] < 0x700000000000:
                    continue
                if not all(values[i+j] == values[i] + 4096*j for j in range(1, 4)):
                    continue
                table = region.base + i * 8 - 0x800
                if table - region.base > 0x100:
                    continue
                guest = cls(host, table)
                try:
                    guest.validate()
                except (ValueError, OSError):
                    continue
                candidates.add(table)
        if len(candidates) != 1:
            raise ValueError(f'Expected one validated page table, found {len(candidates)}')
        return cls(host, candidates.pop())
