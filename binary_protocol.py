import struct as st
import sys


class BinaryProtocol:
    """
    Minimal binary protocol helper.

    The class is derived from the provided reference implementation and keeps the
    parsing methods intact so it can be shared between host and device logic. For
    host-side usage we mainly rely on the command builders (send_set_reg_cmd and
    build_exec_statement_cmd).
    """

    bin_in_proc = False
    bin_cmd_buf = []

    @classmethod
    def handle_input_buf(cls, buf, output_func, reg_bank):
        for idx in range(len(buf)):
            if not cls.bin_in_proc:
                if buf[idx] == 0x11 or buf[idx] == 0x16:
                    cls.bin_in_proc = True
                else:
                    continue

            cb = cls.bin_cmd_buf
            cb.append(buf[idx])
            cb_len = len(cb)
            if cb[0] == 0x16:  # IDLE for simple test
                try:
                    output_func(b"ack")
                except OSError as e:
                    print(f"timeout: IDLE for simple test: {e}")
                cls.bin_in_proc = False
                cb.clear()
            elif cb[0] == 0x11:  # CMD
                if cb_len >= 2:
                    if cb[1] == 0x0 or cb[1] == 0x2:
                        if cb_len >= 7:
                            data_len = st.unpack("<H", bytes(cb[5:7]))[0]
                            if cb_len == 7 + data_len:
                                cls.handle_cmd_buf(cb, data_len, output_func, reg_bank)
                                cls.bin_in_proc = False
                                cb.clear()
                    elif cb[1] == 0x1:  # Get Register
                        if cb_len == 4:
                            cls.handle_cmd_buf(cb, 4, output_func, reg_bank)
                            cls.bin_in_proc = False
                            cb.clear()
                    else:
                        print(f"BIN_CMD: wrong cmd type: {cls.bin_cmd_buf}")
                        cls.bin_in_proc = False
                        cb.clear()
            else:
                print("BIN_CMD: should not reach here!!", cb)
                cls.bin_in_proc = False
                cb.clear()

    @classmethod
    def handle_cmd_buf(cls, cmd_buf, data_len, output_func, reg_bank):
        cb = cmd_buf
        reg_id = st.unpack("<H", bytes(cb[2:4]))[0]
        data = bytes(cb[7 : 7 + data_len])
        if cb[1] == 0x0:  # set register
            if reg_bank.get_register(reg_id) is None:
                print("Set Register ID is not exist!!")
            else:
                if cb[4] == 0x0:  # bool
                    if data_len == 1:
                        val = False if data[0] == 0 else True
                        reg_bank.get_register(reg_id).val = val
                    else:
                        print("BIN_CMD: wrong bool length:", data_len)
                elif cb[4] == 0x1:  # string
                    if data_len != 0:
                        val = data.decode()
                        reg_bank.get_register(reg_id).val = val
                    else:
                        print("BIN_CMD: wrong string length:", data_len)
                elif cb[4] == 0x2:  # int
                    st_format = None
                    if data_len == 1:
                        st_format = "<b"
                    elif data_len == 2:
                        st_format = "<h"
                    elif data_len == 4:
                        st_format = "<i"
                    elif data_len == 8:
                        st_format = "<q"
                    else:
                        print("BIN_CMD: wrong int length:", data_len)

                    if st_format:
                        val = st.unpack(st_format, data)[0]
                        reg_bank.get_register(reg_id).val = val
                elif cb[4] == 0x3:  # unsigned int
                    st_format = None
                    if data_len == 1:
                        st_format = "<B"
                    elif data_len == 2:
                        st_format = "<H"
                    elif data_len == 4:
                        st_format = "<I"
                    elif data_len == 8:
                        st_format = "<Q"
                    else:
                        print("BIN_CMD: wrong unsigned int length:", data_len)

                    if st_format:
                        val = st.unpack(st_format, data)[0]
                        reg_bank.get_register(reg_id).val = val
                elif cb[4] == 0x4:  # float
                    st_format = None
                    if data_len == 4:
                        st_format = "<f"
                    elif data_len == 8:
                        st_format = "<d"
                    else:
                        print("BIN_CMD: wrong float length:", data_len)

                    if st_format:
                        val = st.unpack(st_format, data)[0]
                        reg_bank.get_register(reg_id).val = val
                else:
                    print(f"BIN_CMD: unsupported data type: {cb[4]}")
        elif cb[1] == 0x1:  # get register
            if reg_bank.get_register(reg_id) is None:
                print("Get Register ID is not exist!!")
            else:
                val = reg_bank.get_register(reg_id).val
                print(val)
                cls.send_set_reg_cmd(reg_id, val, output_func)
        elif cb[1] == 0x2:  # execute a statement
            if cb[4] == 0x1:  # string
                if data_len != 0:
                    statement = data.decode()
                    cls.exec_statement_cmd(statement)
                else:
                    print("BIN_CMD: wrong string length:", data_len)
            else:
                print(f"BIN_CMD: wrong statement data type: {hex(cb[4])}")
        else:
            print(f"BIN_CMD: should not reach here: {cb}")

    @staticmethod
    def sim_output_func(buf):
        sender = getattr(sys, "zmq_send", None)
        if callable(sender):
            return sender(buf)
        raise RuntimeError("sys.zmq_send is not available")

    @staticmethod
    def usb_output_func(buf):
        pass

    @staticmethod
    def send_set_reg_cmd(reg_id, val, output_func):
        header = b"\x11\x00"
        reg_field = st.pack("<H", reg_id)

        if type(val) == bool:  # bool
            data = b"\x01" if val is True else b"\x00"
            data_type_field = b"\x00"
        elif type(val) == str:  # string
            data = val.encode()
            data_type_field = b"\x01"
        elif type(val) == float:  # float
            data = st.pack("<d", val)
            data_type_field = b"\x04"
        elif val < 0:  # int
            data = st.pack("<q", val)
            data_type_field = b"\x02"
        else:  # unsigned int
            data = st.pack("<Q", val)
            data_type_field = b"\x03"

        data_len_field = st.pack("<H", len(data))
        try:
            output_func(header + reg_field + data_type_field + data_len_field + data)
        except OSError as e:
            print(f"timeout: send_set_reg_cmd: {e}")

    @staticmethod
    def build_get_reg_cmd(reg_id: int) -> bytes:
        """
        Build a get-register command frame.
        """
        return b"\x11\x01" + st.pack("<H", reg_id)

    @staticmethod
    def build_exec_statement_cmd(statement: str, reg_id: int = 0) -> bytes:
        """
        Build an execute-statement command frame understood by handle_cmd_buf().
        """
        data = statement.encode()
        header = b"\x11\x02"
        reg_field = st.pack("<H", reg_id)
        data_type_field = b"\x01"
        data_len_field = st.pack("<H", len(data))
        return header + reg_field + data_type_field + data_len_field + data

    @staticmethod
    def exec_statement_cmd(statement):
        if statement.find(":") != -1:
            print('BIN_CMD: statement contains ":", execution is ignored.')
            return

        end_idx = statement.find("\n")
        if end_idx == -1:
            print('BIN_CMD: statement does not contain "\\n", execution is ignored.')
            return
        try:
            to_exec = statement[0:end_idx]
            print(f"BIN_CMD: execute {to_exec}")
            exec(to_exec)
        except Exception as exc:  # pragma: no cover - defensive for device side
            print(f"BIN_CMD: exec error: {exc}")
