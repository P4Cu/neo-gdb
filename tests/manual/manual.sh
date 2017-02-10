## This will run nvim then spawn a terminal that runs gdb with our script in it finally putting python-interactive to be ready to
##  start testing manually.
nvim -c ":terminal gdb --init-command=manual.py" -c ":call feedkeys('python-interactive')"
