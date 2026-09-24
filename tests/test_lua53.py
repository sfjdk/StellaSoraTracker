import struct
import unittest

from stellasora_toolkit.lua53 import Lua53Reader, TAG_FLOAT, TAG_INTEGER, TAG_SHORT_STRING


class BufferMemory:
    def __init__(self, size=0x2000):
        self.data = bytearray(size)

    def read(self, address, size):
        if not self.is_readable(address, size):
            raise OSError("outside buffer")
        return bytes(self.data[address : address + size])

    def try_read(self, address, size):
        try:
            return self.read(address, size)
        except OSError:
            return None

    def is_readable(self, address, size=1):
        return 0 <= address and address + size <= len(self.data)

    def tvalue(self, address, value, tag):
        struct.pack_into("<Qi", self.data, address, value, tag)

    def string(self, address, value):
        encoded = value.encode()
        self.data[address + 8] = 4
        self.data[address + 11] = len(encoded)
        self.data[address + 24 : address + 24 + len(encoded)] = encoded


class Lua53ReaderTests(unittest.TestCase):
    def test_decodes_scalar_values(self):
        memory = BufferMemory()
        lua = Lua53Reader(memory)
        memory.tvalue(0x100, 42, TAG_INTEGER)
        memory.data[0x120:0x128] = struct.pack("<d", 0.063)
        struct.pack_into("<i", memory.data, 0x128, TAG_FLOAT)
        self.assertEqual(lua.decode_tvalue(lua.read_tvalue(0x100)), 42)
        self.assertAlmostEqual(lua.decode_tvalue(lua.read_tvalue(0x120)), 0.063)

    def test_reads_hash_table(self):
        memory = BufferMemory()
        lua = Lua53Reader(memory)
        table, nodes, key = 0x100, 0x200, 0x400
        memory.data[table + 8] = 5
        memory.data[table + 11] = 0
        struct.pack_into("<Q", memory.data, table + 24, nodes)
        memory.string(key, "AttrId")
        memory.tvalue(nodes, 3002, TAG_INTEGER)
        memory.tvalue(nodes + 16, key, TAG_SHORT_STRING)
        self.assertEqual(lua.read_table(table), {"AttrId": 3002})

    def test_reads_array_table(self):
        memory = BufferMemory()
        lua = Lua53Reader(memory)
        table, array, nodes = 0x100, 0x300, 0x500
        memory.data[table + 8] = 5
        struct.pack_into("<I", memory.data, table + 12, 2)
        struct.pack_into("<Q", memory.data, table + 16, array)
        struct.pack_into("<Q", memory.data, table + 24, nodes)
        memory.tvalue(array, 132, TAG_INTEGER)
        memory.tvalue(array + 16, 301, TAG_INTEGER)
        self.assertEqual(lua.read_table(table), [132, 301])


if __name__ == "__main__":
    unittest.main()

