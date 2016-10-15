#!/bin/bash

# current dir
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
FILE_INIT=${DIR}/neo-gdbinit
FILE_GDB_INIT=${HOME}/.gdbinit

echo '-------------------------------------------'
echo 'This script will install neo-gdb.'
echo '-------------------------------------------'
echo 'CONFIGURATION:'
echo "DIR: ${DIR}"
echo "FILE_INIT: ${FILE_INIT}"
echo "FILE_GDB_INIT: ${FILE_GDB_INIT}"
echo '-----------------------------------------'

if [ -f $FILE_GDB_INIT ]; then
    echo "$FILE_GDB_INIT already exists moving to *.old"
    if mv ${FILE_GDB_INIT} ${FILE_GDB_INIT}.old; then
        echo "Moved"
    else
        echo ".old already exists! failed"
        exit -1
    fi
fi

echo "Creating link to: ${FILE_INIT}"
if ln -s ${FILE_INIT} ${FILE_GDB_INIT}; then
    echo "Successfully installed"
else
    echo "Failed to create link"
    exit -2
fi
