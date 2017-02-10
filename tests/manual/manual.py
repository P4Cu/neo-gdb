import os
import neovim

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

