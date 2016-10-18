import os
import neovim

# Common methods -----------------------------------------------------------------------------------


class memorize(dict):

    def __init__(self, func):
        self.func = func

    def __call__(self, *args):
        return self[args]

    def __missing__(self, key):
        result = self[key] = self.func(*key)
        return result


def suppress_module(name):
    try:
        del globals()[name]
    except NameError:
        pass


@memorize
def nvim():
    # check if we run from withing of nvim if true we want to debug using nvim
    address = os.getenv('NVIM_LISTEN_ADDRESS')
    if address is not None:
        return neovim.attach('socket', path=address)
    return None


# Module definition --------------------------------------------------------------------------------


class NvimModule(gdb.Command):

    @staticmethod
    def start():
        if nvim():
            o = NvimModule()
            # allow usage with Dashboard script!
            if 'Dashboard' in globals():
                suppress_module('Source')

    def __init__(self):
        self.started = False
        self.file_name = None
        self.ts = None
        self.layout = NvimLayout()

        # init gdb part
        gdb.Command.__init__(self, 'nvim',
                             gdb.COMMAND_USER, gdb.COMPLETE_NONE, True)
        gdb.events.cont.connect(self.on_continue)
        gdb.events.stop.connect(self.on_stop)
        gdb.events.exited.connect(self.on_exit)

        self.define_symbols()

    def on_continue(self, _):
        print('on_continue')

    def on_stop(self, _):
        print('on_stop')

        if not self.started:
            self.started = True
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

    def on_exit(self, _):
        print('on_exit')
        self.started = False
        self.layout.close_all_support_window()

    def define_symbols(self):
        nvim().command('sign define GdbCurrentLine text=⇒')
        nvim().command('sign define GdbBreakpoint text=●')


class NvimWindow(object):
    ''' Abstraction of a window inside Nvim '''

    def __init__(self):
        self._window = None
        self._prev_window = None

    def open(self):
        if not self.valid:
            # remember current to focus it back
            current = nvim().current.window
            # create a split
            nvim().command('split')
            self.window = nvim().current.window
            # focus back
            nvim().current.window = current

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
            nvim().command('sign place 5000 name=GdbCurrentLine line=' + str(line) + ' file=' + filename)
            self.unfocus()


class NvimGdbWindow(NvimWindow):

    def __init__(self, nvim_window, nvim_buffer):
        super().__init__()
        self.window = nvim_window
        self.buffer = nvim_buffer


class NvimBreakpointsWindow(NvimWindow):

    def __init__(self):
        super().__init__()


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
        self.stack = NvimWindow()
        self.breakpoints = NvimBreakpointsWindow()
        self.locals = NvimWindow()

    def create(self):
        if not self._check_if_only_window_on_tab():
            # create a tab
            nvim().command('tabnew')
            nvim().current.buffer = self.gdb.buffer
            self.gdb.window = nvim().current.window
        for name, cmd in NvimLayout.layout:
            nvim().command(cmd)
            nvim().command('setlocal buftype=nofile | setlocal bufhidden=hide |'
                           ' setlocal noswapfile | setlocal nobuflisted')
            # recognize window
            obj = self._win_to_obj(name)
            obj.window = nvim().current.window
            self.all_windows.append(obj)
        # focus back gdb

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
