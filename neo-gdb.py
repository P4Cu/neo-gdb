import os
import sys
import neovim
import threading
import logging
from logging import info, warning, error

logging.getLogger('').handlers = []
logging.basicConfig(level=logging.INFO, filename='/tmp/neo-gdb.log', filemode='w')

# Common methods ---------------------------------------------------------


class memorize(dict):

    def __init__(self, func):
        self.func = func

    def __call__(self, *args):
        return self[args]

    def __missing__(self, key):
        result = self[key] = self.func(*key)
        return result


@memorize
def nvim():
    # check if we run from withing of nvim if true we want to debug using nvim
    address = os.getenv('NVIM_LISTEN_ADDRESS')
    if address is not None:
        return neovim.attach('socket', path=address)
    return None


def gdb_call_into_nvim_mainloop(fn, finalize_with=None):
    """
    Decorator to half sync / half async where the calling thread is the GDB thread and the
     request thread is neovim mainloop thread.
     @param fn Function to call on nvim thread.
     @param finalize_with May be used to do something after the function and right before lock is
             released.
    """
    cv = threading.Condition()

    def gdb_thread_call(*args, **kwargs):
        """
        This will be called on main thread.
        """
        cv.acquire()

        def nvim_thread_call(*args, **kwargs):
            """
            This will be called on Nvim thread.
            """
            cv.acquire()
            if fn:
                fn(*args, **kwargs)
            cv.notify_all()
            cv.release()
        nvim().async_call(nvim_thread_call, *args, **kwargs)
        cv.wait()
        if finalize_with:
            finalize_with()
        cv.release()
    return gdb_thread_call


# Module definition ------------------------------------------------------


class NvimModule(gdb.Command):

    @staticmethod
    def start():
        if nvim():
            o = NvimModule()

    def __init__(self):
        self.started = False
        self.file_name = None
        self.ts = None
        self.layout = NvimLayout()
        self.remote = NvimRemote()
        self.remote.start_loop()

        # Init gdb part
        # All of these will happen in GDB thread so we need to forward it via nvim().async_call
        #  into our thread.
        gdb.Command.__init__(self, 'nvim',
                             gdb.COMMAND_USER, gdb.COMPLETE_NONE, True)
        gdb.events.cont.connect(gdb_call_into_nvim_mainloop(self.on_continue))
        gdb.events.stop.connect(gdb_call_into_nvim_mainloop(self.on_stop))
        gdb.events.exited.connect(gdb_call_into_nvim_mainloop(
            self.on_exit, finalize_with=self.remote.stop_loop))
        gdb.events.breakpoint_created.connect(gdb_call_into_nvim_mainloop(
            self.layout.breakpoints.on_created))
        gdb.events.breakpoint_modified.connect(gdb_call_into_nvim_mainloop(
            self.layout.breakpoints.on_modified))
        gdb.events.breakpoint_deleted.connect(gdb_call_into_nvim_mainloop(
            self.layout.breakpoints.on_deleted))

    def on_continue(self, _):
        pass

    def on_stop(self, _):
        if not self.started:
            self.started = True
            self.define_symbols()
            self.layout.create()

        # use shorter form
        nvim().command('sign unplace 5000')
        # try to fetch the current line (skip if no line information)
        sal = gdb.selected_frame().find_sal()
        current_line = sal.line
        if current_line == 0:
            return None
        # reload the source file if changed
        file_name = sal.symtab.fullname()
        ts = None
        try:
            ts = os.path.getmtime(file_name)
        except:
            pass  # delay error check to open()
        if (file_name != self.file_name or ts and ts > self.ts):
            self.file_name = file_name
            self.ts = ts

        self.layout.source.set_source(file_name, current_line)

        self.layout.stack.lines()
        self.layout.locals.lines()

    def on_exit(self, _):
        self.started = False
        self.layout.close_all_support_window()

    def define_symbols(self):
        nvim().command('sign define GdbCurrentLine text=⇒')
        nvim().command('sign define GdbBreakpoint text=●')


class NvimWindow(object):
    ''' Abstraction of a window inside Nvim '''

    def __init__(self):
        self._window = None
        self._buffer = None
        self._prev_window = None

    def close(self):
        if self.valid:
            self.focus()
            nvim().command('close')
            self.unfocus()
            self.window = None

    def focus(self):
        if self.valid:
            self._prev_window = nvim().current.window
            nvim().current.window = self.window

    def unfocus(self):
        if self._prev_window and self._prev_window.valid:
            nvim().current.window = self._prev_window
        self._prev_window = None

    @property
    def window(self):
        return self._window

    @window.setter
    def window(self, value):
        self._window = value

    @property
    def buffer(self):
        return self._buffer

    @buffer.setter
    def buffer(self, value):
        self._buffer = value

    @property
    def valid(self):
        if self.window and self.window.valid:
            return True
        return False


class NvimSourceWindow(NvimWindow):
    ''' '''

    def __init__(self):
        super().__init__()

    def set_source(self, filename, line):
        if self.valid:
            self.focus()
            nvim().command('edit! +' + str(line) + ' ' + filename)
            nvim().command(
                'sign place 5000 name=GdbCurrentLine line=' +
                str(line) +
                ' file=' +
                filename)
            self.unfocus()


class NvimGdbWindow(NvimWindow):

    def __init__(self, nvim_window, nvim_buffer):
        super().__init__()
        self.window = nvim_window
        self.buffer = nvim_buffer


def format_address(address):
    pointer_size = gdb.parse_and_eval('$pc').type.sizeof
    return ('0x{{:0{}x}}').format(pointer_size * 2).format(address)


def to_unsigned(value, size=8):
    # values from GDB can be used transparently but are not suitable for
    # being printed as unsigned integers, so a conversion is needed
    return int(value.cast(gdb.Value(0).type)) % (2 ** (size * 8))


def to_string(value):
    # attempt to convert an inferior value to string; OK when (Python 3 ||
    # simple ASCII); otherwise (Python 2.7 && not ASCII) encode the string as
    # utf8
    try:
        value_string = str(value)
    except UnicodeEncodeError:
        value_string = unicode(value).encode('utf8')
    return value_string


class NvimStackWindow(NvimWindow):

    def __init__(self):
        super().__init__()

    def lines(self):
        lines = []
        number = 0
        frame = gdb.newest_frame()
        while frame:
            # selected = (frame == gdb.selected_frame())
            frame_id = str(number)
            info = NvimStackWindow.get_pc_line(frame)
            lines.append('[{}] {}'.format(frame_id, info))
            # next
            frame = frame.older()
            number += 1
        self.buffer[:] = lines

    @staticmethod
    def get_pc_line(frame):
        frame_pc = format_address(frame.pc())
        info = 'from {}'.format(frame_pc)
        if frame.name():
            frame_name = frame.name()
            try:
                # try to compute the offset relative to the current function
                value = gdb.parse_and_eval(frame.name()).address
                # it can be None even if it is part of the "stack" (C++)
                if value:
                    func_start = to_unsigned(value)
                    offset = frame.pc() - func_start
                    frame_name += '+' + str(offset)
            except gdb.error:
                pass  # e.g., @plt
            info += ' in {}'.format(frame_name)
            sal = frame.find_sal()
            if sal.symtab:
                file_name = sal.symtab.filename
                file_line = str(sal.line)
                info += ' at {}:{}'.format(file_name, file_line)
        return info


class NvimLocalsWindow(NvimWindow):

    def __init__(self):
        super().__init__()

    def lines(self):
        lines = []
        frames = []
        frame = gdb.selected_frame()
        if frame:
            lines = ['============Arguments===========']
            # fetch frame arguments and locals
            decorator = gdb.FrameDecorator.FrameDecorator(frame)
            # arguments
            frame_args = decorator.frame_args()
            args_lines = self.fetch_frame_info(frame, frame_args, 'arg')
            if args_lines:
                lines.extend(args_lines)
            else:
                lines.append('(no arguments)')
            # Locals
            frame_locals = decorator.frame_locals()
            locals_lines = self.fetch_frame_info(frame, frame_locals, 'loc')
            if locals_lines:
                res = ['=============Locals=============']
                for line in locals_lines:
                    res.extend(line.split('\n'))
                lines.extend(res)
            else:
                lines.append('(no locals)')
        self.buffer[:] = lines

    def fetch_frame_info(self, frame, data, prefix):
        lines = []
        try:
            for elem in data or []:
                name = elem.sym
                value = to_string(elem.sym.value(frame))
                lines.append('{} {} = {}'.format(prefix, name, value))
        except gdb.MemoryError as e:
            # TODO: this may fail as argument are kept on stack and something happens there
            #  see http://stackoverflow.com/a/31317730/4296448
            error('Fetch frame failed: %s', e)
        return lines


class NvimBreakpointsWindow(NvimWindow):

    def update_breakpoints(self, current=None):
        lines = []
        breakpoints = gdb.breakpoints()
        for bp in breakpoints:
            if bp is current:
                lines.append('[[{}]] {}'.format(bp.number, bp.location))
            else:
                lines.append('[{}] {}'.format(bp.number, bp.location))
        if self.buffer is not None:
            self.buffer[:] = lines

    def on_created(self, _):
        info('on_created')
        self.update_breakpoints()

    def on_modified(self, bp):
        if bp is not None:
            info('on_modified %s', bp)
        else:
            info('on_modified')
        self.update_breakpoints(current=bp)

    def on_deleted(self, _):
        info('on_deleted')
        self.update_breakpoints()


class NvimLayout(object):

    # first window is always GDB
    layout = [('stack', 'rightbelow vsplit STACK'),
              ('breakpoints', 'rightbelow vsplit BREAKPOINTS'),
              ('source', 'botright 40split CODE'),
              ('locals', 'rightbelow 80vsplit LOCALS')]

    def __init__(self):
        self.all_windows = []
        self.gdb = NvimGdbWindow(nvim().current.window, nvim().current.buffer)
        self.source = NvimSourceWindow()
        self.stack = NvimStackWindow()
        self.breakpoints = NvimBreakpointsWindow()
        self.locals = NvimLocalsWindow()

    def create(self):
        if not self._check_if_only_window_on_tab():
            # create a tab
            nvim().command('tabnew')
            nvim().current.buffer = self.gdb.buffer
            self.gdb.window = nvim().current.window
        for name, cmd in NvimLayout.layout:
            nvim().command(cmd)
            nvim().command(
                'setlocal buftype=nofile | setlocal bufhidden=hide |'
                ' setlocal noswapfile | setlocal nobuflisted')
            # recognize window
            obj = self._win_to_obj(name)
            obj.window = nvim().current.window
            obj.buffer = nvim().current.buffer
            self.all_windows.append(obj)
        self.gdb.focus()

    def _check_if_only_window_on_tab(self):
        return 1 == nvim().eval('winnr(\'$\')')

    def _win_to_obj(self, name):
        return {'source': self.source,
                'stack': self.stack,
                'breakpoints': self.breakpoints,
                'locals': self.locals
                }[name]

    def close_all_support_window(self):
        for win in self.all_windows:
            win.close()
        self.all_windows = []


class NvimRemote(object):
    """
    This object represents a thread that runs nvim RPC main-loop and receives notifications/events
     from nvim.
    There's not need to synchronize resources as python GIL (Global Interpreter Lock) won't allow
     two threads to run concurrently.
    """

    def __init__(self):
        self.thread = threading.Thread(
            target=self._mainloop,
            name='neogdb_nvim_receiver')

    def start_loop(self):
        """
        This will start mainloop in thread.
        """
        if not self.thread.isAlive():
            info("Starting mainloop")
            self.thread.start()
            info("Started mainloop channel_id={}".format(nvim().channel_id))

    def stop_loop(self):
        """
        This will shutdown the thread properly.
        """
        info("Stop receiver")

        def stop_loop_impl():
            """
            We have to call it from the mainloop thread. Easiest way is to do that via
             neovim async_call method.
            """
            info("stop_loop_impl started")
            nvim().stop_loop()
            info("stop_loop_impl finished")
        if self.thread.isAlive():
            nvim().async_call(stop_loop_impl)
            info("Join mainloop")
            self.thread.join(5.0)
            info("Joined mainloop")

    def _mainloop(self):
        def request_cb(name, args):
            info("Received cb={} with args={}".format(name, args))
            if name == "nvim_receiver_stop":
                info("Stopping loop from request")
                nvim().stop_loop()
                info("Stopped loop from request")
            return None
        nvim().run_loop(request_cb=request_cb, notification_cb=None)
        info("Loop stopped")

# --------------------------------------------------------------------------------------------------
# Author:
#  Copyright (c) 2016 Andrzej Pacanowski <andrzej.pacanowski@gmail.com>
# With inspiration of gdb-dashboard
#  https://github.com/cyrus-and/gdb-dashboard
#  Copyright (c) 2015-2016 Andrea Cardaci <cyrus.and@gmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ------------------------------------------------------------------------------
# vim: filetype=python
# Local Variables:
# mode: python
# End:
