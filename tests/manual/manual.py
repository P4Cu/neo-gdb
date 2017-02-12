import os
import neovim
import threading
import code

print()
vim = neovim.attach('socket', path=os.getenv('NVIM_LISTEN_ADDRESS'))
print('vim=', vim)
cid = vim.channel_id
print('cid=', cid)


def test_call_and_reply():
    def setup_cb():
        cmd = 'let g:result = rpcrequest(%d, "client-call", 1, 2, 3)' % cid
        print("Calling `{}`".format(cmd))
        vim.command(cmd)
        print("Expected vim.vars['result'] [4,5,6]")
        print("After vim.vars['result']", vim.vars['result'])
        vim.stop_loop()

    def request_cb(name, args):
        print("Received cb={} with args={}", name, args)
        if name == 'client-call':
            print("Expected args [1,2,3]")
            print("Return [4,5,6]")
            return [4, 5, 6]

    vim.run_loop(request_cb, None, setup_cb)
    # vim.run_loop(None, None, None)

nvim_receiver = None


def start_receiver():
    def receiver_loop():
        def request_cb(name, args):
            print("Received cb={} with args={}", name, args)
            if name == "nvim_receiver_stop":
                print("Stopping loop from request")
                vim.stop_loop()
                print("Stopped loop from request")
            return [1, 2, 3]
        vim.run_loop(request_cb=request_cb, notification_cb=None)
        print("Loop stopped")
    global nvim_receiver
    nvim_receiver = threading.Thread(
        target=receiver_loop, name='nvim_receiver')
    print("starting")
    nvim_receiver.start()
    print("started")


def nvim_callback(name):
    cmd = "let g:result = rpcrequest({}, \"{}\")".format(cid, name)
    print("Calling `{}`".format(cmd))
    vim.command(cmd)
    print("After vim.vars['result']", vim.vars['result'])


def stop_receiver():
    global nvim_receiver
    print("Stop receiver")
    vim.vars['x'] = 666

    def stop_receiver_impl():
        print("stop_receiver_impl started")
        vim.stop_loop()
        print("stop_receiver_impl finished")
    vim.async_call(stop_receiver_impl)
    print("Join nvim_receiver")
    nvim_receiver.join(30.0)
    print("joined")


def interpreter_in_thread():
    print("before interpter")
    nvim_receiver = threading.Thread(
        target=code.interact, name='nvim_receiver')
    print("before start")
    nvim_receiver.start()
    print("before run_loop")

    def request_cb(name, args):
        print("Received cb={} with args={}", name, args)
        if name == "nvim_receiver_stop":
            print("Stopping loop from request")
            vim.stop_loop()
            print("Stopped loop from request")
        return [1, 2, 3]
    vim.run_loop(request_cb=request_cb, notification_cb=None)
    print("Loop stopped")
