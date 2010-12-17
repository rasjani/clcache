#!/usr/bin/env python
#
# clcache.py - a compiler cache for Microsoft Visual Studio
#
# Copyright (c) 2010, Frerich Raabe <raabe@froglogic.com>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the <organization> nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
import json
import os
from shutil import copyfile, rmtree
import subprocess
from subprocess import Popen, PIPE, STDOUT
import sys

class ObjectCache:
    def __init__(self):
        try:
            self.dir = os.environ["CLCACHE_DIR"]
        except KeyError:
            self.dir = os.path.join(os.path.expanduser("~"), "clcache")
        if not os.path.exists(self.dir):
            os.mkdir(self.dir)

    def cacheDirectory(self):
        return self.dir

    def clean(self, stats, maximumSize):
        currentSize = stats.currentCacheSize()
        if currentSize < maximumSize:
            return

        objects = [os.path.join(root, "object")
                   for root, folder, files in os.walk(self.dir)
                   if "object" in files]

        objectInfos = [(os.path.getatime(fn), fn) for fn in objects]

        objectsByATime = sorted(objectInfos, key=lambda t: t[0], reverse=True)

        for atime, fn in objectsByATime:
            objectSize = os.path.getsize(fn)
            cacheDir, fileName = os.path.split( fn )
            rmtree(cacheDir)
            currentSize -= objectSize
            if currentSize < maximumSize:
                break

        stats.setCacheSize(currentSize)

    def computeKey(self, compilerBinary, commandLine):
        ppcmd = list(commandLine)
        ppcmd[0] = compilerBinary
        ppcmd.remove("/c")
        ppcmd.append("/EP")
        preprocessor = Popen(ppcmd, stdout=PIPE, stderr=open(os.devnull, 'w'))
        preprocessedSourceCode = preprocessor.communicate()[0]

        normalizedCmdLine = self.__normalizedCommandLine(commandLine[1:])

        import hashlib
        sha = hashlib.sha1()
        sha.update(str(long(os.path.getmtime(compilerBinary))))
        sha.update(str(os.path.getsize(compilerBinary)))
        sha.update(' '.join(normalizedCmdLine))
        sha.update(preprocessedSourceCode)
        return sha.hexdigest()

    def hasEntry(self, key):
        return os.path.exists(self.cachedObjectName(key))

    def setEntry(self, key, objectFileName, compilerOutput):
        if not os.path.exists(self.__cacheEntryDir(key)):
            os.makedirs(self.__cacheEntryDir(key))
        copyfile(objectFileName, self.cachedObjectName(key))
        open(self.__cachedCompilerOutputName(key), 'w').write(compilerOutput)

    def cachedObjectName(self, key):
        return os.path.join(self.__cacheEntryDir(key), "object")

    def cachedCompilerOutput(self, key):
        return open(self.__cachedCompilerOutputName(key), 'r').read()

    def __cacheEntryDir(self, key):
        return os.path.join(self.dir, key[:2], key)

    def __cachedCompilerOutputName(self, key):
        return os.path.join(self.__cacheEntryDir(key), "output.txt")

    def __normalizedCommandLine(self, cmdline):
        def isRelevantArgument(arg):
            for preprocessorArg in [ "/AI", "/C", "/E", "/P", "/FI", "/u", "/X",
                                     "/FU", "/D", "/EP", "/Fx", "/U", "/I" ]:
                if arg[:len(preprocessorArg)] == preprocessorArg:
                    return False
            return True
        return filter(isRelevantArgument, cmdline)

class PersistentJSONDict:
    def __init__(self, fileName):
        self._dirty = False
        self._dict = {}
        self._fileName = fileName
        try:
            self._dict = json.load(open(self._fileName, 'r'))
        except:
            pass

    def __del__(self):
        if self._dirty:
            json.dump(self._dict, open(self._fileName, 'w'))

    def __setitem__(self, key, value):
        self._dict[key] = value
        self._dirty = True

    def __getitem__(self, key):
        return self._dict[key]

    def __contains__(self, key):
        return key in self._dict

class Configuration:
    _defaultValues = { "MaximumCacheSize": 1024 * 1024 * 1000 }

    def __init__(self, objectCache):
        self._cfg = PersistentJSONDict(os.path.join(objectCache.cacheDirectory(),
                                                    "config.txt"))
        for setting, defaultValue in self._defaultValues.iteritems():
            if not setting in self._cfg:
                self._cfg[setting] = defaultValue

    def maximumCacheSize(self):
        return self._cfg["MaximumCacheSize"]

    def setMaximumCacheSize(self, size):
        self._cfg["MaximumCacheSize"] = size

class CacheStatistics:
    def __init__(self, objectCache):
        self._stats = PersistentJSONDict(os.path.join(objectCache.cacheDirectory(),
                                                      "stats.txt"))
        for k in ["InappropriateInvocations", "CacheEntries", "CacheSize",
                  "CacheHits", "CacheMisses"]:
            if not k in self._stats:
                self._stats[k] = 0

    def numInappropriateInvocations(self):
        return self._stats["InappropriateInvocations"]

    def registerInappropriateInvocation(self):
        self._stats["InappropriateInvocations"] += 1

    def numCacheEntries(self):
        return self._stats["CacheEntries"]

    def registerCacheEntry(self, size):
        self._stats["CacheEntries"] += 1
        self._stats["CacheSize"] += size

    def currentCacheSize(self):
        return self._stats["CacheSize"]

    def setCacheSize(self, size):
        self._stats["CacheSize"] = size

    def numCacheHits(self):
        return self._stats["CacheHits"]

    def registerCacheHit(self):
        self._stats["CacheHits"] += 1

    def numCacheMisses(self):
        return self._stats["CacheMisses"]

    def registerCacheMiss(self):
        self._stats["CacheMisses"] += 1

def findCompilerBinary():
    try:
        path = os.environ["CLCACHE_CL"]
        if os.path.exists(path):
            return path
    except KeyError:
        for dir in os.environ["PATH"].split(os.pathsep):
            path = os.path.join(dir, "cl.exe")
            if os.path.exists(path):
                return path
    return None


def printTraceStatement(msg):
    if "CLCACHE_LOG" in os.environ:
        print "*** clcache.py: " + msg


def analyzeCommandLine(cmdline):
    foundCompileOnlySwitch = False
    sourceFile = None
    outputFile = None
    for arg in cmdline[1:]:
        if arg == "/link":
            return (False, None, None)
        elif arg == "/c":
            foundCompileOnlySwitch = True
        elif arg[:3] == "/Fo":
            outputFile = arg[3:]
        elif arg[0] != '/':
            if sourceFile:
                return (False, None, None)
            sourceFile = arg
    if not outputFile and sourceFile:
        srcFileName = os.path.basename(sourceFile)
        outputFile = os.path.join(os.getcwd(),
                                  os.path.splitext(srcFileName)[0] + ".obj")
    return foundCompileOnlySwitch and sourceFile, sourceFile, outputFile


def invokeRealCompiler(compilerBinary, captureOutput=False):
    realCmdline = [compilerBinary] + sys.argv[1:]
    returnCode = None
    output = None
    if captureOutput:
        compilerProcess = Popen(realCmdline, stdout=PIPE, stderr=STDOUT)
        output = compilerProcess.communicate()[0]
        returnCode = compilerProcess.returncode
    else:
        returnCode = subprocess.call(realCmdline)
    return returnCode, output


if len(sys.argv) == 2 and sys.argv[1] == "--help":
    print "clcache.py v0.1"
    print "  --help   : show this help"
    print "  -s       : print cache statistics"
    print "  -M <size>: set maximum cache size (in bytes)"
    sys.exit(0)

if len(sys.argv) == 2 and sys.argv[1] == "-s":
    cache = ObjectCache()
    stats = CacheStatistics(cache)
    cfg = Configuration(cache)
    print "clcache statistics:"
    print "  current cache dir  : " + cache.cacheDirectory()
    print "  cache size         : " + str(stats.currentCacheSize()) + " bytes"
    print "  maximum cache size : " + str(cfg.maximumCacheSize()) + " bytes"
    print "  cache entries      : " + str(stats.numCacheEntries())
    print "  cache hits         : " + str(stats.numCacheHits())
    print "  cache misses       : " + str(stats.numCacheMisses())
    print "  inappr. invocations: " + str(stats.numInappropriateInvocations())
    sys.exit(0)

if len(sys.argv) == 3 and sys.argv[1] == "-M":
    cache = ObjectCache()
    cfg = Configuration(cache)
    cfg.setMaximumCacheSize(int(sys.argv[2]))
    sys.exit(0)

compiler = findCompilerBinary()

if "CLCACHE_DISABLE" in os.environ:
    sys.exit(invokeRealCompiler(compiler)[0])

appropriateForCaching, sourceFile, outputFile = analyzeCommandLine(sys.argv)

cache = ObjectCache()
stats = CacheStatistics(cache)
if not appropriateForCaching:
    stats.registerInappropriateInvocation()
    sys.exit(invokeRealCompiler(compiler)[0])

cachekey = cache.computeKey(compiler, sys.argv)
if cache.hasEntry(cachekey):
    stats.registerCacheHit()
    printTraceStatement("Reusing cached object for key " + cachekey + " for " +
                        "output file " + outputFile)
    copyfile(cache.cachedObjectName(cachekey), outputFile)
    sys.stdout.write(cache.cachedCompilerOutput(cachekey))
    sys.exit(0)
else:
    stats.registerCacheMiss()
    returnCode, compilerOutput = invokeRealCompiler(compiler, captureOutput=True)
    if returnCode == 0:
        printTraceStatement("Adding file " + outputFile + " to cache using " +
                            "key " + cachekey)
        cache.setEntry(cachekey, outputFile, compilerOutput)
        stats.registerCacheEntry(os.path.getsize(outputFile))
        cfg = Configuration(cache)
        cache.clean(stats, cfg.maximumCacheSize())
    sys.stdout.write(compilerOutput)
    sys.exit(returnCode)


