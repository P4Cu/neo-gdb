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
        self.file_name = None
        self.ts = None
        self.code_window = NvimWindow()

        # TODO: is it required?
        self.gdb_window = NvimWindow()
        self.gdb_window = nvim().current.window
        # TODO: is it required?
        self.gdb_buffer = nvim().current.buffer

        self.code_window.create()

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

        current_window = nvim().current.window
        self.code_window.focus()
        nvim().command('edit! +' + str(current_line) + ' ' + self.file_name)
        nvim().current.window = current_window
        nvim().command('sign place 5000 name=GdbCurrentLine line=' + str(current_line) + ' file=' + self.file_name)

    def on_exit(self, _):
        print('on_exit')

    def define_symbols(self):
        nvim().command('sign define GdbCurrentLine text=⇒')
        nvim().command('sign define GdbBreakpoint text=●')


class NvimWindow(object):
    ''' Abstraction of a window inside Nvim '''

    def __init__(self):
        self._window = None

    def create(self):
        # remember current to focus it back
        current = nvim().current.window
        # create a split
        nvim().command('split')
        self.window = nvim().current.window
        # focus back
        nvim().current.window = current

    def focus(self):
        nvim().current.window = self.window

    @property
    def window(self):
        return self._window

    @window.setter
    def window(self, value):
        self._window = value


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
