import pandas as pd
import ast
from collections import defaultdict
import colorama
import math
import re
import warnings
import time
import numpy as np
import sys
import serial
import visa
from command import Command

'''
Lucas Koerner, 2018/4/17
TODO correct docstring format
'''

# TODO:
#   instrument error log lookup: (import as csv?)
#   automatic checker: send values out of range and read-back, note precisions, etc.
#   automatic documentation generator: just as Bluesky? (Sphinx)
#   organization of classes, what inherits from what? Override RS232 init stuff
#   help for each method
#

#   help print to HTML:

convert_lookup = defaultdict(lambda: str)
convert_lookup['str'] = str
convert_lookup['string'] = str
convert_lookup['float'] = float
convert_lookup['double'] = float
convert_lookup['int'] = int
convert_lookup['nan'] = str


def conv_arr_str(str_in):
    """ convert string such as '2.3', '5.4', '9.9' to a list of floats """
    return list(map(lambda x: float(x), str_in.split(',')))

def str_strip(str_in):
    return str_in.rstrip()


convert_lookup['str'] = str_strip
convert_lookup['array'] = conv_arr_str

divider_string = '=====================================\n'

# will want to find byte for certain bit
# will want to find bit for certain name
# will want to find name of certain bit
lia_status = {'serial_poll': ['SCN', 'IFC', 'ERR', 'LIA', 'MAV', 'ESB', 'SRQ', 'unused'],
              'status': ['RSRV/INPT', 'FILTR', 'OUTPT', 'UNLK', 'RANGE', 'TC', 'TRIG', 'unused'],
              'event_status': ['INP', 'unused', 'QRY', 'unused', 'EXE', 'CMD', 'URQ', 'PON'],
              'error': ['unused', 'BACKUP', 'RAM', 'unused', 'ROM', 'GPIB', 'DSP', 'MATH']}


class SCPI(object):
    """A SCPI instrument with a list of commands. The instrument has methods to get and set info of each command.

    Parameters
    ----------
    cmd_list : Command
        A list of commands. Each command is an object of the class Command
    write : method 
        A function that writes data to the hardware interface.
        Examples are pySerial write() or pyvisa inst.write()
    ask : method 
        a function that queries data from the hardware interface (typically a sequence of write and then read).
        Examples are pySerial ask() and pyvisa inst.query()
    name : str, optional
        Name of the instrument 
    """

    def __init__(self, cmd_list, write, ask, name='not named'):
        self._cmds = {}
        for cmd in cmd_list:
            self._cmds[cmd.name] = cmd
        self.write = write
        self.ask = ask
        try:
            name = self.get('id')
        except:
            print('id command not configured. Name set to: {}'.format(name))
        self.instrument_name = name

    def __dir__(self):
        # dir(lia) --> returns a list of the keys
        return self._cmds.keys()

    def __len__(self):
        return len(self._cmds)

    def __getitem__(self, index):
        # TODO: keep or remove?
        # check if this is actually a getter
        if not self._cmds[index].getter:
            # if its not a getter send the command
            #   (i.e. this is a setter without an input parameter)
            self.write(self._cmds[index].ascii_str)
            return

        if self._cmds[index].getter_inputs is not 0:
            return  # TODO --> figure out what to do here

        ret_val = self.ask(self._cmds[index].ascii_str + '?')

        # convert to the specified getter_type (e.g number string to float)
        try:
            return self._cmds[index].getter_type(ret_val)
        except ValueError:
            print('Warning! getter {} returned unexpected type'.format(
                self._cmds[index].name))
            print('  Returned {}; with type = {}; expects = {}'.format(ret_val,
                                                                       type(ret_val), self._cmds[index].getter_type))

        return ret_val

    def __setitem__(self, index, value=None):

        # if value is None we just send the command (e.g. *IDN)
        if value is None:
            self.write(self._cmds[index].ascii_str)

        # check range
        ok = False
        # store in variable to reduce typing
        set_range = self._cmds[index].setter_range
        if set_range is not None:
            if len(set_range) < 2:
                print('Error: Setter range length {} is less than 2'.format(
                    self._cmds[index].name))
                print(' if range check will not be used set to None')
                return -1
            if len(set_range) == 2:
                if all((isinstance(x, float) or isinstance(x, int)) for x in set_range):
                    # check inequalities
                    ok = (set_range[0] <= value) and (set_range[1] >= value)
            else:  # set_range is NOT a list of two numeric values, assume need to check for membership
                ok = value in set_range
        if ok:
            self.write(self._cmds[index].ascii_str + ' {}'.format(value))
            return
        else:
            print(f'Error: value of = {value} not in range ({set_range}) for {colorama.Fore.GREEN}{self._cmds[index].name}{colorama.Style.RESET_ALL} command')
            return -1

    def get(self, name, configs={}):

        if not self._cmds[name].getter:
            print('This command {} is not a getter'.format(name))
            raise NotImplementedError

        cmd_str = self._cmds[name].ascii_str_get
        ret_val = self.ask(cmd_str.format(**configs))

        try:
            val = self._cmds[name].getter_type(ret_val)
            # check if a lookup table exists
            # TODO: input parameter to skip converting to the lookup table?
            if self._cmds[name].lookup is not None:
                try:
                    # check if this value matches a key in the lookup table
                    val = list(self._cmds[name].lookup.keys())[
                        list(self._cmds[name].lookup.values()).index(val)]
                except ValueError:
                    print(
                        'Warning: {} value of {} not in the lookup table'.format(name, val))
            return val

        except ValueError:
            print('Warning! getter {} returned unexpected type'.format(
                self._cmds[name].name))
            print('  Returned {}; with type = {}; expects = {}'.format(ret_val,
                                                                       type(ret_val), self._cmds[name].getter_type))

    def set(self, value, name, configs={}):
        cmd_str = self._cmds[name].ascii_str

        if value is not None:
            # check if this value is a key in the lookup table
            if value in self._cmds[name].lookup:
                try:
                    value = self._cmds[name].lookup[value]
                except:
                    pass  # just keep value

            self.check_set_range(value, name)
            cmd_str = cmd_str.format(value=value, **configs)

        # allow for a setter with no value (e.g. '*RST')
        else:  # is the value is None
            cmd_str = cmd_str.format(value='').rstrip()

        # send the command to the instrument
        self.write(cmd_str)

    def check_set_range(self, value, name):
        ''' check if the value to be set is within range '''
        if (len(self._cmds[name].setter_range) == 2) and (type(self._cmds[name].setter_range) is not str):
            # numeric, check if less than or greater than
            if (value >= self._cmds[name].setter_range[0]) and (value <= self._cmds[name].setter_range[1]):
                return True
            else:
                # throw out of range warning
                self.out_of_range_warning(value, name)
                return False

        else:  # could be a list of strings, check if strings
            if type(self._cmds[name].setter_range[0]) is str:
                # check if value is a member
                if value in self._cmds[name].setter_range:
                    return True
                else:
                    return False
            else:
                # throw out of range warning
                self.out_of_range_warning(value, name)
                return False

    def out_of_range_warning(self, value, name):
        warnings.warn('\n  {} value of {} is out of the range of {}'.format(
            name, value, self._cmds[name].setter_range), UserWarning)

    def set_with_dict(self, D):
        # TODO: remove?
        """ set attributes with a dict """
        for k in D.keys():
            self.__setattr__(k, D[k])

    def list_cmds(self):
        for key in self._cmds:
            print('{}'.format(self._cmds[key].name))

    def help_all(self, subsystem_list=None):

        if subsystem_list is None:
            # get all subsystems
            subsystems = [self._cmds[d].subsystem for d in self._cmds]
            # create a list of unique subsystems
            subsystem_set = set(subsystems)
        else:
            subsystem_set = set(subsystem_list)

        for s in subsystem_set:
            print(divider_string)
            print(f'Help for Subsytem: {colorama.Fore.RED}{s}{colorama.Style.RESET_ALL}:')
            print('\n')
            for k in self._cmds:
                if self._cmds[k].subsystem == s:
                    self.help(k)
                    print('')

    def help(self, index):
        if self._cmds[index].subsystem is not None:
            sub_sys = ' in subsystem: {}'.format(self._cmds[index].subsystem)
        else:
            sub_sys = ''

        print(f'Help for command {colorama.Fore.GREEN}{self._cmds[index].name}{colorama.Style.RESET_ALL}{sub_sys}:')
        print('    {}'.format(self._cmds[index].doc))
        if self._cmds[index].setter_range is not None:
            print('    Allowable range is: {}'.format(
                self._cmds[index].setter_range))
            if len(self._cmds[index].set_config_keys) > 0:
                print('    The setter needs a configuration dictionary with keys: {}'.format(
                    ', '.join(self._cmds[index].set_config_keys)))

        if self._cmds[index].getter:
            print('    Returns: {}'.format(
                self._cmds[index].getter_type.__name__))
            if len(self._cmds[index].set_config_keys) > 0:
                print('    Getting a value needs a configuration dictionary with keys: {}'.format(
                    ', '.join(self._cmds[index].get_config_keys)))

        if len(self._cmds[index].lookup) > 0:
            print('   This command utilizes a lookup table on get and set:')
            print('     ' + str(self._cmds[index].lookup))

    def log_all_getters(self, filename=None, suppress_stdout=False):
        # TODO - get getters with needed configurations
        keys = []
        results = []
        for key in self._cmds:
            if self._cmds[key].getter and (self._cmds[key].getter_inputs == 0):
                keys.append(key)
                results.append(self.get(key))

        # print to stdout if not suppressed
        if not suppress_stdout:
            for (key, result) in zip(keys, results):
                print('{} = {}'.format(key, result))

        # write to a file if a file name is provided as input
        if filename is not None:
            with open(filename, 'w') as f:
                print('Time = {}'.format(time.time()), file=f)
                print('Instrument = {}'.format(self.instrument_name), file=f)
                for (key, result) in zip(keys, results):
                    print('{} = {}'.format(key, result), file=f)

        return dict(zip(keys, results))

    def read_comm_err(self, reg_name='event_status', bit_name='CMD'):
        ''' This is specific to SRS810 and must be over-riden by each instrument '''
        reg_val = self.get(reg_name)
        return bool(self.get_bit(reg_val, lia_status[reg_name].index(bit_name)))

    def get_bit(self, value, bit):
        bit_val = 1 if (value & 2**(bit) != 0) else 0
        return bit_val

    def set_bit(self, value, bit):
        return (value | 2**bit)

    def clear_bit(self, value, bit):
        return (value & ((2**8 - 1) - bit**2))

    def test_command(self, name, set_vals=None):

        ok = True
        allowed_err = 0.02

        if (len(self._cmds[name].get_config_keys) > 0) or (len(self._cmds[name].set_config_keys) > 0):
            print('Skipping test of {}'.format(name))
            print(
                '  Test of getters or setters that require a configuration input are not yet implemented')
            return False

        # if getter and setter
        if (self._cmds[name].getter and self._cmds[name].setter):

            ret = self.get(name)
            ok |= self.read_comm_err()
            if set_vals is None:
                set_vals = [self._cmds[name].setter_range[0],
                            self._cmds[name].setter_range[1]]

            for set_val in set_vals:
                self.set(set_val, name)
                ok |= self.read_comm_err()
                ret = self.get(name)
                ok |= self.read_comm_err()
                if self._cmds[name].getter_type == float:
                    try:
                        deviates = np.abs((ret - set_val) /
                                          set_val) > allowed_err
                    except ZeroDivisionError:
                        deviates = (ret != set_val)
                else:
                    deviates = (ret != set_val)

                    if deviates:
                        ok = False
                        if self._cmds[name].getter_type == float:
                            print('Get vs. set difference greater than {} %% for command {}'.format(
                                allowed_err * 100, name))
                        else:
                            print(
                                'Get vs. set difference for command {}'.format(name))
                        print('Set {}; got {}'.format(set_val, ret))
                        print(divider_string)

        # if setter only
        elif self._cmds[name].setter:
            if (self._cmds[name].setter_range) is None:
                set_val = None
            elif (len(self._cmds[name].setter_range) == 2):
                set_val = self._cmds[name].setter_range[0]
            else:
                print('Skipping test of setter {}'.format(name))
                return False

            self.set(set_val, name)
            ok |= self.read_comm_err()

        # if getter only
        elif self._cmds[name].getter:
            ret = self.get(name)
            ok |= self.read_comm_err()

        else:
            print('Command is not a setter nor a getter, cannot test!')

        return ok

    def test_all(self, skip_subsystem=['setup', 'status'], skip_commands=['fast_transfer', 'reset']):
        ''' test all commands '''

        all_tests = {}
        for key in self._cmds:
            if (self._cmds[key].subsystem in skip_subsystem) or (key in skip_commands):
                pass
            else:
                print('Testing {}'.format(key))
                status = self.test_command(key)
                all_tests[key] = status
                print('Result for {} = {}'.format(key, status))

        return all_tests


class SCPI_Test(object):
    # TODO
    """ test each setter/getter combination """
    # check range, set and then get
    # check error codes
    # test each getter 
    # test each setter 
    # test each misc 
    pass


def open_visa(addr):
    """ open a VISA object 

    .. todo::

       * determine if error flag
       * enable or disable of lookup table   

    """

    mgr = visa.ResourceManager()
    resources = mgr.list_resources()
    if addr in resources:
        # open device 
        # TODO check return value 
        obj = mgr.open_resource(addr)
    elif addr not in resources:
        print('Trying to open the device even though it was not found by the resource manager')
        obj = mgr.open_resource(addr)
    else:
        print('This address {} was not recognized'.format(addr), file=sys.stderr)
        print('Returning an empty handle', file=sys.stderr)
        obj = None
    return obj


class USB(object):

    def __init__(self, address):
        self.instr = open_visa(address)

    def ask(self, cmd):
        res = self.instr.query(cmd)
        return res

    def write(self, cmd):
        return self.instr.write(cmd)

    def close(self):
        pass

    # https://stackoverflow.com/questions/16470903/pyserial-2-6-specify-end-of-line-in-readline
    def _readline(self):
        eol = b'\r'
        leneol = len(eol)
        line = bytearray()
        while True:
            c = self.ser.read(1)
            if c:
                line += c
                if line[-leneol:] == eol:
                    break
            else:
                break
        return bytes(line)


class RS232(object):

    # TODO: make the Lock-in specific stuff inherit the RS232 object
    def __init__(self, ser_port):
        self.ser = serial.Serial(
            port=ser_port,
            baudrate=9600,
            parity=serial.PARITY_NONE,
            bytesize=serial.EIGHTBITS)
        self.terminator = ' \n'
        self.ser_port = ser_port
        self.open()

        # lock-in specific
        self.write('OUTX 0')  # set to RS232
        print(self.ask("*IDN?").decode('utf-8'))

    def open(self):
        self.ser.close()
        self.ser.open()

        cnt = 0
        while not self.ser.isOpen():
            time.sleep(0.1)
            cnt = cnt + 1
            if cnt > 25:
                print('Failed to open RS232 interface at address: {}'.format(
                    self.ser_port))

    def ask(self, cmd):
        self.write(cmd)
        res = self._readline()
        return res

    def write(self, cmd):
        cmd = cmd + self.terminator
        self.ser.write(cmd.encode('utf-8'))

    def close(self):
        self.ser.close()

    # https://stackoverflow.com/questions/16470903/pyserial-2-6-specify-end-of-line-in-readline
    def _readline(self):
        eol = b'\r'
        leneol = len(eol)
        line = bytearray()
        while True:
            c = self.ser.read(1)
            if c:
                line += c
                if line[-leneol:] == eol:
                    break
            else:
                break
        return bytes(line)


def init_instrument(cmd_map, use_serial=True, use_usb=False, addr=None):

    # Read CSV file and
    df = pd.read_csv(cmd_map)
    df = df.rename(columns=lambda x: x.strip())  # strip column headers only

    df['setter_type'] = df['setter_type'].str.strip()
    df['getter_type'] = df['getter_type'].str.strip()

    # TODO read lookup table CSV

    cmd_list = []
    for index, row in df.iterrows():
        # convert getter, setter to Boolean True or False
        for gs in ['getter', 'setter']:
            if row[gs] in ['True', 'T', 'TRUE', 'true', True]:
                tmp = True
            elif row[gs] in ['False', 'F', 'FALSE', 'false', False]:
                tmp = False
            else:
                tmp = False
            row[gs] = tmp  # converts to Boolean

        if row['setter_range'] is not None:
            try:
                row['setter_range'] = ast.literal_eval(row['setter_range'])
            except:
                print(f'Warning setter_range of {colorama.Fore.GREEN}{row["setter_range"]}{colorama.Style.RESET_ALL} for command {colorama.Fore.BLUE}{row["name"]}{colorama.Style.RESET_ALL} not of proper form')
                row['setter_range'] = None

        # pandas read default value is nan. Convert to None or 0 depending upon column
        def mod_default(row_el, default_value):
            try:
                row_el = default_value if math.isnan(row_el) else row_el
            except TypeError:
                row_el = row_el

            return row_el

        row['setter_inputs'] = mod_default(row['setter_inputs'], None)
        row['getter_inputs'] = mod_default(row['getter_inputs'], 0)
        row['ascii_str_get'] = mod_default(row['ascii_str_get'], None)

        cmd = Command(name=row['name'], ascii_str=row['ascii_str'], ascii_str_get=row['ascii_str_get'],
                      getter=row['getter'], getter_type=convert_lookup[row['getter_type']],
                      setter=row['setter'], setter_type=convert_lookup[row['setter_type']],
                      setter_range=row['setter_range'],
                      doc=row['doc'], subsystem=row['subsystem'],
                      getter_inputs=row['getter_inputs'], setter_inputs=row['setter_inputs'])

        cmd_list.append(cmd)

    if use_serial:
        inst_comm = RS232(addr)
        inst_comm.ser.flush()
        inst = SCPI(cmd_list, inst_comm.write, inst_comm.ask)

    elif use_usb:
        inst_comm = USB(addr)
        inst = SCPI(cmd_list, inst_comm.write, inst_comm.ask)

    else:  # allow for debugging without instruments attached: use print to stdout, always return '7'
        inst_comm = None

        def ask(str_input):
            print(str_input)
            return '7'

        def write(str_input):
            print(str_input)

        inst = SCPI(cmd_list, write, ask)

    return inst, inst_comm

# -------------------- JUNK CODE ------------------
# scpi.set_with_dict(scpi._cmds) <--- nice to have tab-complete, but


# check to see if these header values are populated
# for now remove this and require that these column headers are populated
try:
    doc = row['doc']
except:
    doc = None
try:
    subsystem = row['subsystem']
except:
    subsystem = None
