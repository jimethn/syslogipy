#!/usr/bin/env python

"""Syslogger is a configurable daemon for converting apps that use
non-standard logging facilities to use the unix standard syslog. It
can trace individual files or watch a directory.

To use it, you must create a config file and pass it to the run_config
function. Syslogger will then handle the rest, creating objects to log
the targets to syslog according to the configuration. If directory or
trace logging is used, the program will continue to log according to
the configuration until a KeyboardInterrupt or SIGINT is received.

A sample script using Syslogger may look like:

#!/usr/bin/env python
import syslogger
syslogger.run_config("mine.conf")

"""
__version__ = "0.9.0"
__author__ = "Jonathan Lynch (http://tektosterone.com)"
__copyright__ = "(C) 2011 Jonathan Lynch. Code under FreeBSD License."


import os
import time
import re
import signal
import syslog
import ConfigParser


def run_config(conf):
    """Create and execute Sysloggers according to the configuration.

    The configuration is an ini-style text file. Section headings are
    either a file or directory, and have different options depending
    on which one. All options may be omitted. Lines beginning with #
    or ; are ignored. File paths are relative to the directory from
    which syslogger is run.

    A sample configuration file may look like:
    
    [/path/to/file]
    # t means trace, o means one-time (default)
    mode = t
    
    [/path/to/directory]
    # log any files ending in "log" or "log.1" (default is blank: all files)
    filetypes = log, log.1
    # check for new logs every 5.5 minutes (default is 0: no checking)
    interval = 5m30s
    # delete processed logs that are more than a week old (default)
    backlog = 7d

    """
    global loggers # contains the created Syslogger objects

    def handle_dir(path):
        """Get the config options and create the DirSyslogger."""
        t = DirSyslogger(path,
                         config.get(path, "filetypes").split(','),
                         config.get(path, "interval"),
                         config.get(path, "backlog"))
        loggers.append(t)

    def handle_file(path):
        """Get the config options and create the FileSyslogger."""
        if not config.has_option(path, "mode"):
            raise ConfigError(path, "no mode option configured")
        mode = config.get(path, "mode")
        if mode == "trace" or mode == "t": mode = 't'
        elif mode == "one-time" or mode == "o": mode = 'o'
        else: raise ConfigError(path, "invalid mode given: " + mode)
        t = FileSyslogger(path, mode)
        loggers.append(t)

    loggers = []
    config = ConfigParser.SafeConfigParser({'filetypes':'',
                                            'interval':0,
                                            'backlog':'7d'})
    config.read(conf)
    for sec in config.sections():
        if os.path.isdir(sec):
            handle_dir(sec)
        elif os.path.isfile(sec):
            handle_file(sec)
        else: raise ConfigError(sec, "not a file or directory")
    try:
        while True:
            for logger in loggers:
                logger.run()
    except KeyboardInterrupt:
        print "interrupt received. exiting..."


class FileSyslogger(object):
    """Log a file to syslog. It can either trace the file indefinitely
    or dump the contents in one go. The name of the file will be used
    as the file's ident for syslog.

    """
    def __init__(self, file, mode='o'):
        """Initialize the FileSyslogger.

        Arguments:
            file -- the path to the file to syslog
            mode -- the logging mode to use, o(ne-time) or t(race)

        """
        self.file = file
        self.mode = mode
        print self.file
        self.fd = open(self.file)
        self.p = syslog.LOG_INFO | syslog.LOG_LOCAL7

    def run(self):
        syslog.openlog(str(self.file), 0, self.p)
        if self.mode == 'o':
            self.__log_file()
            self.mode = 'x'
        elif self.mode == 'x': return # x means one-time logging has occurred
        elif self.mode == 't': self.__log_file()
        else: raise ArgumentError("mode", self.mode, "invalid mode")

    def __log_file(self):
        """Dump the contents of the file to syslog."""
        while True:
            line = self.fd.readline()
            if not line: break
            syslog.syslog(self.p, line)


class DirSyslogger(object):
    """Log a directory to syslog. Searches the directory for files
    that end in one of a given set of extensions. Each file is logged
    to syslog and is then prepended with an underscore. If a matching
    file already has an underscore, it will delete it if it is older
    than the backlog interval. If an interval is defined, it will
    sleep until the next cycle then repeat the process.

    """
    def __init__(self, dir, filetypes, interval, backlog):
        """Initialize the DirSyslogger.

        Arguments:
            dir -- the path to the directory to syslog
            filetypes -- a list of file extensions to log
            interval -- how often to re-check the dir, 0 means never
            backlog -- how long to keep processed logs before deletion

        * backlog and interval are both in the format '5y4d3h2m1s'

        """
        self.dir = dir
        self.filetypes = filetypes
        self.interval = str(interval)
        self.backlog = backlog
        self.sleeptime = timestring_to_seconds(self.interval)
        self.lastrun = 0

    def run(self):
        """Perform directory logging if the interval has passed."""
        if self.sleeptime == -1: return
        if (time.time() - self.lastrun) > self.sleeptime:
            self.lastrun = time.time()
            self.__process_dir()
        if self.sleeptime == 0: self.sleeptime = -1 # we've ran once

    def __is_old(self, file):
        """Return true if the file is older than the backlog period."""
        changed = os.path.getctime(file)
        now = time.time()
        return now - changed > timestring_to_seconds(self.backlog)

    def __process_dir(self):
        """Run through the directory, logging, renaming, and deleting logs."""
        for file in os.listdir(self.dir):
            logthis = False
            fullpath = os.path.normpath(self.dir + '/' + file)
            # check if we care about this file
            for type in self.filetypes:
                if file.endswith(type):
                    logthis = True
            if len(self.filetypes) == 0:
                logthis = True
            if os.path.isdir(fullpath):
                logthis = False
            if not logthis: continue
            # we care, so handle the file
            if file.startswith('_'): # delete old files with underscores
                if self.__is_old(fullpath):
                    os.remove(fullpath)
            else: # process and underscore new files
                t = FileSyslogger(fullpath, 'o')
                t.run()
                newname = os.path.normpath(os.path.dirname(fullpath) + "/_" + \
                                           os.path.basename(fullpath))
                os.rename(fullpath, newname)


class Error(Exception):
    """The base class for exceptions in this module."""
    pass


class ConfigError(Error):
    """Exception raised for errors in the configuration.

    Attributes:
        sect -- configuration section in which the error occurred
        msg  -- explanation of the error

    """
    def __init__(self, sect, msg):
        self.sect = sect
        self.msg = msg
    def __str__(self):
        return '%s: %s' % (self.sect, self.msg)


class ArgumentError(Error):
    """Exceptions raised for invalid arguments to classes and methods.

    Attributes:
        arg   -- argument that was being parsed
        value -- value that raised the exception
        msg   -- explanation of the error

    """
    def __init__(self, arg, value, msg):
        self.arg = arg
        self.value = value
        self.msg = msg
    def __str__(self):
        return 'invalid value %s for argument %s: %s' % \
               (self.value, self.arg, self.msg)


def timestring_to_seconds(timestring):
    """Takes a timestring in the form e.g. 3d7h30m12s and returns seconds."""
    time_re = re.compile(r"^((?P<years>[0-9]+)y)?((?P<days>[0-9]+)d)?" + \
                         r"((?P<hours>[0-9]+)h)?((?P<minutes>[0-9]+)m)?" + \
                         r"((?P<seconds>[0-9]+)s)?")
    try:
        m = time_re.match(timestring).groupdict('0')
    except AttributeError, e:
        raise ArgumentError("timestring", timestring, "invalid format")
    return 31536000 * int(m['years']) + 86400 * int(m['days']) + \
           3600 * int(m['hours']) + 60 * int(m['minutes']) + int(m['seconds'])
