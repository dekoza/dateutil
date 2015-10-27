# This code was originally contributed by Jeffrey Harris.
import datetime
import struct

import ctypes
from ctypes import wintypes

from six.moves import winreg

from .__init__ import tzname_in_python2

__all__ = ["tzwin", "tzwinlocal"]

ONEWEEK = datetime.timedelta(7)

TZKEYNAMENT = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Time Zones"
TZKEYNAME9X = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Time Zones"
TZLOCALKEYNAME = r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation"


class tzres(object):
    p_wchar = ctypes.POINTER(wintypes.WCHAR)        # Pointer to a wide char

    def __init__(self, tzres_loc='tzres.dll'):
        # Load the user32 DLL so we can load strings from tzres
        user32 = ctypes.WinDLL('user32')
        
        # Specify the LoadStringW function
        user32.LoadStringW.argtypes = (wintypes.HINSTANCE,
                                       wintypes.UINT,
                                       wintypes.LPWSTR,
                                       wintypes.c_int)

        self.LoadStringW = user32.LoadStringW
        self._tzres = ctypes.WinDLL(tzres_loc)
        self.tzres_loc = tzres_loc

    def load_name(offset):
        resource = self.p_wchar()
        lpBuffer = ctypes.cast(ctypes.byref(resource), wintypes.LPWSTR)
        nchar = self.LoadStringW(self._tzres._handle, offset, lpBuffer, 0)
        return resource[:nchar]

    def name_from_string(tzname_str):
        offset = -1 * int(tzname_str.split(',')[-1])
        return load_name(offset)

# Cache tzres object
_TZRES = None
def _get_tzres(tzres_loc):
    global _TZRES
    if _TZRES is None or _TZRES.tzres_loc != tzres_loc:
        _TZRES = tzres()

    return _TZRES

def _settzkeyname():
    handle = winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE)
    try:
        winreg.OpenKey(handle, TZKEYNAMENT).Close()
        TZKEYNAME = TZKEYNAMENT
    except WindowsError:
        TZKEYNAME = TZKEYNAME9X
    handle.Close()
    return TZKEYNAME

TZKEYNAME = _settzkeyname()


class tzwinbase(datetime.tzinfo):
    """tzinfo class based on win32's timezones available in the registry."""

    def utcoffset(self, dt):
        if self._isdst(dt):
            return datetime.timedelta(minutes=self._dstoffset)
        else:
            return datetime.timedelta(minutes=self._stdoffset)

    def dst(self, dt):
        if self._isdst(dt):
            minutes = self._dstoffset - self._stdoffset
            return datetime.timedelta(minutes=minutes)
        else:
            return datetime.timedelta(0)

    @tzname_in_python2
    def tzname(self, dt):
        if self._isdst(dt):
            return self._dstname
        else:
            return self._stdname

    def list():
        """Return a list of all time zones known to the system."""
        handle = winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE)
        tzkey = winreg.OpenKey(handle, TZKEYNAME)
        result = [winreg.EnumKey(tzkey, i)
                  for i in range(winreg.QueryInfoKey(tzkey)[0])]
        tzkey.Close()
        handle.Close()
        return result
    list = staticmethod(list)

    def display(self):
        return self._display

    def _isdst(self, dt):
        if not self._dstmonth:
            # dstmonth == 0 signals the zone has no daylight saving time
            return False
        dston = picknthweekday(dt.year, self._dstmonth, self._dstdayofweek,
                               self._dsthour, self._dstminute,
                               self._dstweeknumber)
        dstoff = picknthweekday(dt.year, self._stdmonth, self._stddayofweek,
                                self._stdhour, self._stdminute,
                                self._stdweeknumber)
        if dston < dstoff:
            return dston <= dt.replace(tzinfo=None) < dstoff
        else:
            return not dstoff <= dt.replace(tzinfo=None) < dston


class tzwin(tzwinbase):

    def __init__(self, name):
        self._name = name

        # multiple contexts only possible in 2.7 and 3.1, we still support 2.6
        with winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE) as handle:
            if name.startswith('@tzres'):
                tzres_obj = _get_tzres()
                name = tzres_obj.name_from_string(name)

            with winreg.OpenKey(handle,
                                "%s\%s" % (TZKEYNAME, name)) as tzkey:
                keydict = valuestodict(tzkey)

        self._stdname = keydict["Std"]
        self._dstname = keydict["Dlt"]

        self._display = keydict["Display"]

        # See http://ww_winreg.jsiinc.com/SUBA/tip0300/rh0398.htm
        tup = struct.unpack("=3l16h", keydict["TZI"])
        self._stdoffset = -tup[0]-tup[1]          # Bias + StandardBias * -1
        self._dstoffset = self._stdoffset-tup[2]  # + DaylightBias * -1

        # for the meaning see the win32 TIME_ZONE_INFORMATION structure docs
        # http://msdn.microsoft.com/en-us/library/windows/desktop/ms725481(v=vs.85).aspx
        (self._stdmonth,
         self._stddayofweek,   # Sunday = 0
         self._stdweeknumber,  # Last = 5
         self._stdhour,
         self._stdminute) = tup[4:9]

        (self._dstmonth,
         self._dstdayofweek,   # Sunday = 0
         self._dstweeknumber,  # Last = 5
         self._dsthour,
         self._dstminute) = tup[12:17]

    def __repr__(self):
        return "tzwin(%s)" % repr(self._name)

    def __reduce__(self):
        return (self.__class__, (self._name,))


class tzwinlocal(tzwinbase):
    def __init__(self):
        with winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE) as handle:

            with winreg.OpenKey(handle, TZLOCALKEYNAME) as tzlocalkey:
                keydict = valuestodict(tzlocalkey)

            self._stdname = keydict["StandardName"]
            self._dstname = keydict["DaylightName"]
            self._tzkeyname = keydict["TimeZoneKeyName"]
            try:
                with winreg.OpenKey(
                        handle, "%s\%s" % (TZKEYNAME, self._tzkeyname)) as tzkey:
                    _keydict = valuestodict(tzkey)
                    self._display = _keydict["Display"]
            except OSError:
                self._display = None

        self._stdoffset = -keydict["Bias"]-keydict["StandardBias"]
        self._dstoffset = self._stdoffset-keydict["DaylightBias"]

        # See http://ww_winreg.jsiinc.com/SUBA/tip0300/rh0398.htm
        tup = struct.unpack("=8h", keydict["StandardStart"])

        (self._stdmonth,
         self._stddayofweek,   # Sunday = 0
         self._stdweeknumber,  # Last = 5
         self._stdhour,
         self._stdminute) = tup[1:6]

        tup = struct.unpack("=8h", keydict["DaylightStart"])

        (self._dstmonth,
         self._dstdayofweek,   # Sunday = 0
         self._dstweeknumber,  # Last = 5
         self._dsthour,
         self._dstminute) = tup[1:6]

    def __reduce__(self):
        return (self.__class__, ())


def picknthweekday(year, month, dayofweek, hour, minute, whichweek):
    """dayofweek == 0 means Sunday, whichweek 5 means last instance"""
    first = datetime.datetime(year, month, 1, hour, minute)
    weekdayone = first.replace(day=((dayofweek-first.isoweekday()) % 7+1))
    for n in range(whichweek):
        dt = weekdayone+(whichweek-n)*ONEWEEK
        if dt.month == month:
            return dt


def valuestodict(key):
    """Convert a registry key's values to a dictionary."""
    dout = {}
    size = winreg.QueryInfoKey(key)[1]
    tz_res = None

    for i in range(size):
        key, value, dtype = winreg.EnumValue(key, i)

        if dtype == winreg.REG_DWORD or dtype == REG_DWORD_LITTLE_ENDIAN:
            # If it's a DWORD (32-bit integer), it's stored as unsigned - convert
            # that to a proper signed integer
            if value & (1 << 31):
                value = value - (1 << 32)
        elif dtype == winreg.REG_SZ:
            # If it's a reference to the tzres DLL, load the actual string
            if value.startswith('@tzres')):
                tz_res = tz_res or tzres()
                value = tz_res.name_from_string(value)

            value = value.rstrip('\x00')    # Remove trailing nulls

        dout[key] = value

    return dout
