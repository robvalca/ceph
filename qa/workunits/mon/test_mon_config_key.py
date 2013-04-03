#!/usr/bin/python
#
# test_mon_config_key - Test 'ceph config-key' interface
#
# Copyright (C) 2013 Inktank
#
# This is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License version 2.1, as published by the Free Software
# Foundation.  See file COPYING.
#
import sys
import os
import base64
import time
import errno
import random
import subprocess
import string
import logging
import argparse


#
# Accepted Environment variables:
#   CEPH_TEST_VERBOSE     - be more verbose; '1' enables; '0' disables
#   CEPH_TEST_DURATION    - test duration in seconds
#   CEPH_TEST_SEED        - seed to be used during the test
#
# Accepted arguments and options (see --help):
#   -v, --verbose         - be more verbose
#   -d, --duration SECS   - test duration in seconds
#   -s, --seed SEED       - seed to be used during the test
#


LOG = logging.getLogger(os.path.basename(sys.argv[0].replace('.py','')))

SIZES = [
    (0, 0),
    (10, 0),
    (25, 0),
    (50, 0),
    (100, 0),
    (1000, 0),
    (4096, 0),
    (4097, -errno.EFBIG),
    (8192, -errno.EFBIG)
    ]

OPS = {
      'put':['existing','new'],
      'del':['existing','enoent'],
      'exists':['existing','enoent'],
      'get':['existing','enoent']
      }

CONFIG_PUT = []       #list: keys
CONFIG_DEL = []       #list: keys
CONFIG_EXISTING = {}  #map: key -> size

def run_cmd(cmd, expects=0):
    full_cmd = [ 'ceph', 'config-key' ] + cmd

    if expects < 0:
        expects = -expects

    cmdlog = LOG.getChild('run_cmd')
    cmdlog.debug('{fc}'.format(fc=' '.join(full_cmd)))

    proc = subprocess.Popen(full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)

    stdout = []
    stderr = []
    while True:
        try:
            (out, err) = proc.communicate()
            if out is not None:
                stdout += str(out).split('\n')
                cmdlog.debug('stdout: {s}'.format(s=out))
            if err is not None:
                stdout += str(err).split('\n')
                cmdlog.debug('stderr: {s}'.format(s=err))
        except ValueError:
            ret = proc.wait()
            break

    if ret != expects:
        cmdlog.error('cmd > {cmd}'.format(cmd=full_cmd))
        cmdlog.error('expected return \'{expected}\' got \'{got}\''.format(
            expected=expects,got=ret))
        cmdlog.error('stdout')
        for i in stdout:
            cmdlog.error('{x}'.format(x=i))
        cmdlog.error('stderr')
        for i in stderr:
            cmdlog.error('{x}'.format(x=i))

#end run_cmd

def gen_data(size, rnd):
    chars = string.ascii_letters + string.digits
    return ''.join(rnd.choice(chars) for i in range(size))

def gen_key(rnd):
    return gen_data(20, rnd)

def gen_tmp_file_path(rnd):
    file_name = gen_data(20, rnd)
    file_path = os.path.join('/tmp', 'ceph-test.'+file_name)
    return file_path

def destroy_tmp_file(fpath):
    if os.path.exists(fpath) and os.path.isfile(fpath):
        os.unlink(fpath)

def write_data_file(data, rnd):
    file_path = gen_tmp_file_path(rnd)
    data_file = open(file_path, 'wr+')
    data_file.truncate()
    data_file.write(data)
    data_file.close()
    return file_path
#end write_data_file

def choose_random_op(rnd):
    op = rnd.choice(OPS.keys())
    sop = rnd.choice(OPS[op])
    return (op, sop)


def parse_args(args):
    parser = argparse.ArgumentParser(
        description='Test the monitor\'s \'config-key\' API',
        )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='be more verbose',
        )
    parser.add_argument(
        '-s', '--seed',
        metavar='SEED',
        help='use SEED instead of generating it in run-time',
        )
    parser.add_argument(
        '-d', '--duration',
        metavar='SECS',
        help='run test for SECS seconds (default: 300)',
        )
    parser.set_defaults(
        seed=None,
        duration=300,
        verbose=False,
        )
    return parser.parse_args(args)

def main():

    args = parse_args(sys.argv[1:])

    verbose = args.verbose
    if os.environ.get('CEPH_TEST_VERBOSE') is not None:
        verbose = (os.environ.get('CEPH_TEST_VERBOSE') == '1')

    duration = int(os.environ.get('CEPH_TEST_DURATION', args.duration))
    seed = os.environ.get('CEPH_TEST_SEED', args.seed)
    seed = int(time.time()) if seed is None else int(seed)

    rnd = random.Random()
    rnd.seed(seed)

    loglevel = logging.INFO
    if verbose:
        loglevel = logging.DEBUG

    logging.basicConfig(level=loglevel,)

    LOG.info('seed: {s}'.format(s=seed))

    start = time.time()

    while (time.time() - start) < duration:
        (op, sop) = choose_random_op(rnd)

        LOG.info('{o}({s})'.format(o=op, s=sop))
        opLOG = LOG.getChild('{o}({s})'.format(o=op, s=sop))

        if op == 'put':
            via_file = (rnd.uniform(0, 100) < 50.0)

            expected = 0
            cmd = [ 'put' ]
            key = None

            if sop == 'existing':
                if len(CONFIG_EXISTING) == 0:
                    opLOG.debug('no existing keys; continue')
                    continue
                key = rnd.choice(CONFIG_PUT)
                assert key in CONFIG_EXISTING, \
                    'key \'{k_}\' not in CONFIG_EXISTING'.format(k_=key)

                expected = 0 # the store just overrides the value if the key exists
            #end if sop == 'existing'
            elif sop == 'new':
                for x in xrange(0, 10):
                    key = gen_key(rnd)
                    if key not in CONFIG_EXISTING:
                        break
                    key = None
                if key is None:
                    opLOG.error('unable to generate an unique key -- try again later.')
                    continue

                assert key not in CONFIG_PUT and key not in CONFIG_EXISTING, \
                    'key {k} was not supposed to exist!'.format(k=key)

            assert key is not None, \
                'key must be != None'

            cmd += [ key ]

            (size, error) = rnd.choice(SIZES)
            if size > 25:
                via_file = True

            data = gen_data(size, rnd)
            if error == 0: # only add if we expect the put to be successful
                if sop == 'new':
                    CONFIG_PUT.append(key)
                CONFIG_EXISTING[key] = size
            expected = error

            if via_file:
                data_file = write_data_file(data, rnd)
                cmd += [ '-i', data_file ]
            else:
                cmd += [ data ]

            opLOG.debug('size: {sz}, via: {v}'.format(
                sz=size,
                v='file: {f}'.format(f=data_file) if via_file == True else 'cli')
                )
            run_cmd(cmd, expects=expected)
            if via_file:
                destroy_tmp_file(data_file)
            continue

        elif op == 'del':
            expected = 0
            cmd = [ 'del' ]
            key = None

            if sop == 'existing':
                if len(CONFIG_EXISTING) == 0:
                    opLOG.debug('no existing keys; continue')
                    continue
                key = rnd.choice(CONFIG_PUT)
                assert key in CONFIG_EXISTING, \
                    'key \'{k_}\' not in CONFIG_EXISTING'.format(k_=key)

            if sop == 'enoent':
                for x in xrange(0, 10):
                    key = base64.b64encode(os.urandom(20))
                    if key not in CONFIG_EXISTING:
                        break
                    key = None
                if key is None:
                    opLOG.error('unable to generate an unique key -- try again later.')
                    continue
                assert key not in CONFIG_PUT and key not in CONFIG_EXISTING, \
                    'key {k} was not supposed to exist!'.format(k=key)
                expected = 0  # deleting a non-existent key succeeds

            assert key is not None, \
                'key must be != None'

            cmd += [ key ]
            opLOG.debug('key: {k}'.format(k=key))
            run_cmd(cmd, expects=expected)
            if sop == 'existing':
                CONFIG_DEL.append(key)
                CONFIG_PUT.remove(key)
                del CONFIG_EXISTING[key]
            continue

        elif op == 'exists':
            expected = 0
            cmd = [ 'exists' ]
            key = None

            if sop == 'existing':
                if len(CONFIG_EXISTING) == 0:
                    opLOG.debug('no existing keys; continue')
                    continue
                key = rnd.choice(CONFIG_PUT)
                assert key in CONFIG_EXISTING, \
                    'key \'{k_}\' not in CONFIG_EXISTING'.format(k_=key)

            if sop == 'enoent':
                for x in xrange(0, 10):
                    key = base64.b64encode(os.urandom(20))
                    if key not in CONFIG_EXISTING:
                        break
                    key = None
                if key is None:
                    opLOG.error('unable to generate an unique key -- try again later.')
                    continue
                assert key not in CONFIG_PUT and key not in CONFIG_EXISTING, \
                    'key {k} was not supposed to exist!'.format(k=key)
                expected = -errno.ENOENT

            assert key is not None, \
                'key must be != None'

            cmd += [ key ]
            opLOG.debug('key: {k}'.format(k=key))
            run_cmd(cmd, expects=expected)
            continue

        elif op == 'get':
            expected = 0
            cmd = [ 'get' ]
            key = None

            if sop == 'existing':
                if len(CONFIG_EXISTING) == 0:
                    opLOG.debug('no existing keys; continue')
                    continue
                key = rnd.choice(CONFIG_PUT)
                assert key in CONFIG_EXISTING, \
                    'key \'{k_}\' not in CONFIG_EXISTING'.format(k_=key)

            if sop == 'enoent':
                for x in xrange(0, 10):
                    key = base64.b64encode(os.urandom(20))
                    if key not in CONFIG_EXISTING:
                        break
                    key = None
                if key is None:
                    opLOG.error('unable to generate an unique key -- try again later.')
                    continue
                assert key not in CONFIG_PUT and key not in CONFIG_EXISTING, \
                    'key {k} was not supposed to exist!'.format(k=key)
                expected = -errno.ENOENT

            assert key is not None, \
                'key must be != None'

            file_path = gen_tmp_file_path(rnd)
            cmd += [ key, '-o', file_path ]
            opLOG.debug('key: {k}'.format(k=key))
            run_cmd(cmd, expects=expected)
            if sop == 'existing':
                try:
                    f = open(file_path, 'r+')
                except IOError as err:
                    if err.errno == errno.ENOENT:
                        assert CONFIG_EXISTING[key] == 0, \
                            'error opening \'{fp}\': {e}'.format(fp=file_path,e=err)
                        continue
                    else:
                        assert False, \
                            'some error occurred: {e}'.format(e=err)
                cnt = 0
                while True:
                    l = f.read()
                    if l == '':
                        break
                    cnt += len(l)
                assert cnt == CONFIG_EXISTING[key], \
                    'wrong size from store for key \'{k}\': {sz}, expected {es}'.format(
                        k=key,sz=cnt,es=CONFIG_EXISTING[key])
                destroy_tmp_file(file_path)
            continue
        else:
            assert False, 'unknown op {o}'.format(o=op)

    # check if all keys in 'CONFIG_PUT' exist and
    # if all keys on 'CONFIG_DEL' don't.
    # but first however, remove all keys in CONFIG_PUT that might
    # be in CONFIG_DEL as well.
    config_put_set = set(CONFIG_PUT)
    config_del_set = set(CONFIG_DEL).difference(config_put_set)

    LOG.info('perform sanity checks on store')

    for k in config_put_set:
        LOG.getChild('check(puts)').debug('key: {k_}'.format(k_=k))
        run_cmd(['exists', k], expects=0)
    for k in config_del_set:
        LOG.getChild('check(dels)').debug('key: {k_}'.format(k_=k))
        run_cmd(['exists', k], expects=-errno.ENOENT)


if __name__ == "__main__":
    main()
