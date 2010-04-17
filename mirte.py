from __future__ import with_statement

import threading
import optparse
import logging
import os.path
import socket
import select
import yaml
import sys
import os

class Module(object):
	def __init__(self, settings, logger):
		for k, v in settings.items():
			setattr(self, k, v)
		self.l = logger
		self.on_settings_changed = dict()
	
	def change_setting(self, key, value):
		setattr(self, key, value)
		if not key in self.on_settings_changed:
			return
		self.on_settings_changed[key]()

	def register_on_setting_changed(self, key, handler):
		if not key in self.on_settings_changed:
			self.on_settings_changed[key] = Event()
		self.on_settings_changed[key].register(handler)

class Event(object):
	def __init__(self):
		self.handlers = []
	def register(self, handler):
		self.handlers.append(handler)
	def __call__(self, *args, **kwargs):
		for handler in self.handlers:
			handler(*args, **kwargs)

def _get_by_path(bits, _globals):
	c = None
	for i, bit in enumerate(bits):
		try:
			c = globals()[bit] if c is None else getattr(c, bit)
		except (AttributeError, KeyError):
			c = __import__('.'.join(bits[:i+1]), _globals,
				fromlist=[bits[i+1]] if i+1 < len(bits) else [])
	return c

def get_by_path(path, _globals=None):
	""" Returns an object by <path>, importing modules if necessary """
	if _globals is None: _globals = list()
	return _get_by_path(path.split('.'), _globals)

def restricted_cover(l, succsOf):
	""" Returns a restricted <succsOf> which only takes and yields
	    values from <l> """
	fzl = frozenset(l)
	lut = dict()
	for i in l:
		lut[i] = fzl.intersection(succsOf(i))
	return lambda x: lut[x]

def dual_cover(l, succsOf):
	""" <succsOf> assigns to each element of <l> a list of successors.
	    This function returns the dual, "predsOf" if you will. """ 
	lut = dict()
	for i in l:
		lut[i] = list()
	for i in l:
		for j in succsOf(i):
			lut[j].append(i)
	return lambda x: lut[x]
		
def sort_by_successors(l, succsOf):
	""" Sorts a list, such that if l[b] in succsOf(l[a]) then a < b """
	rlut = dict()
	nret = 0
	todo = list()
	for i in l:
		rlut[i] = set()
	for i in l:
		for j in succsOf(i):
			rlut[j].add(i)
	for i in l:
		if len(rlut[i]) == 0:
			todo.append(i)
	while len(todo) > 0:
		i = todo.pop()
		nret += 1
		yield i
		for j in succsOf(i):
			rlut[j].remove(i)
			if len(rlut[j]) == 0:
				todo.append(j)
	if nret != len(l):
		raise ValueError, "Cycle detected"

class InstanceInfo(object):
	def __init__(self, name, module, obj, settings, deps):
		self.deps = deps
		self.settings = settings
		self.name = name
		self.object = obj
		self.module = module

class VSettingDefinition(object):
	def __init__(self, default=None, _type=None):
		self.default = default
		self.type = _type

class DepDefinition(object):
	def __init__(self, _type=None):
		self.type = _type

class ModuleDefinition(object):
	def __init__(self, deps=None, vsettings=None, implementedBy=None,
			run=False, inherits=None):
		self.deps = dict() if deps is None else deps
		self.vsettings = dict() if vsettings is None else vsettings
		self.implementedBy = implementedBy
		self.run = run
		self.inherits = inherits if inherits is None else list()
	
	@property
	def abstract(self):
		return self.implementedBy is None

class Manager(Module):
	def __init__(self, logger=None):
		if logger is None:
			logger = logging.getLogger(object.__repr__(self))
		super(Manager, self).__init__({}, logger)
		self.running = False
		self.modules = dict()
		self.to_stop = list() # objects to stop
		self.daemons = list() # and to join
		self.valueTypes = {'str': str,
				   'float': float,
				   'int': int}
		self.insts = dict()
		self._sleep_socketpair = socket.socketpair()
		self.add_module_definition('module', ModuleDefinition())
		self.add_module_definition('manager', ModuleDefinition())
		self.insts['manager'] = InstanceInfo('manager', 'manager',
						     self, {}, {})
	
	def add_module_definition(self, name, definition):
		if name in self.modules:
			raise ValueError, "Duplicate module name"
		self.modules[name] = definition
	
	def create_instance(self, name, moduleName, settings):
		""" Creates an instance of <moduleName> at <name> with
		    <settings>. """
		if name in self.insts:
			raise ValueError, \
				"There's already an instance named %s" % \
						name
		if not moduleName in self.modules:
			raise ValueError, \
				"There's no module %s" % moduleName
		md = self.modules[moduleName]
		deps = dict()
		for k, v in md.deps.iteritems():
			if not k in settings:
				raise ValueError, "Missing setting %s" % k
			if not settings[k] in self.insts:
				raise ValueError, "No such instance %s" \
						% settings[k]
			deps[k] = settings[k]
			settings[k] = self.insts[settings[k]].object
		for k, v in md.vsettings.iteritems():
			if not k in settings:
				self.l.warn('%s:%s not set' % 
						(name, k))
		cl = get_by_path(md.implementedBy)
		il = logging.getLogger(name)
		self.l.info('create_instance %-15s %s' % (
				name, md.implementedBy))
		obj = cl(settings, il)
		self.insts[name] = InstanceInfo(name,moduleName, obj,
						settings, deps)
		if md.run:
			self.to_stop.append(name)
			self.daemons.append(name)
		elif hasattr(obj, 'stop'):
			self.to_stop.append(name)
	
	def run(self):
		def _daemon_entry(ii):
			try:
				ii.object.run()
			except Exception:
				self.l.exception(("Module %s exited "+
						  "abnormally") % ii.name)
				return
			self.l.info("Module %s exited normally" % ii.name)
		assert not self.running
		self.running = True
		# Note that self.daemons is already dependency ordered for us
		for name in self.daemons:
			ii = self.insts[name]
			ii.thread = threading.Thread(target=_daemon_entry,
						     args=[ii])
			ii.thread.start()
		while self.running:
			try:
				select.select([self._sleep_socketpair[1]],
					      [], [])
			except KeyboardInterrupt:
				self.l.warn("Keyboard interrupt")
				self.running = False
				break
			self.l.info("Woke up from select")
		self.l.info("Stopping modules")
		for name in reversed(self.to_stop):
			ii = self.insts[name]
			self.l.info("  %s" % ii.name)
			ii.object.stop()
		self.l.info("Joining modules")
		for name in reversed(self.daemons):
			ii = self.insts[name]
			self.l.info("  %s" % ii.name)
			ii.thread.join()
	
	def change_setting(self, instance_name, key, raw_value):
		""" Change the settings <key> to <raw_value> of an instance
		    named <instance_name>.  <raw_value> should be a string and
		    is properly converted. """
		ii = self.insts[instance_name]
		mo = self.modules[ii.module]
		if key in mo.deps:
			if not raw_value in self.insts:
				raise ValueError, "No such instance %s" % \
						raw_value
			vii = self.insts[raw_value]
			vmo = self.modules[vii.module]
			if not (mo.deps[key].type in vmo.inherits or
					mo.deps[key].type == vii.module):
				raise ValueError, "%s isn't a %s" % (
						raw_value, mo.deps[key].type)
			value = vii.object
		elif key in mo.vsettings:
			value = self.valueTypes[mo.vsettings[key].type](
					raw_value)
		else:
			raise ValueError, "No such settings %s" % key
		self.l.info("Changing %s.%s to %s" % (instance_name,
						      key,
						      raw_value))
		ii.settings[key] = value
		ii.object.change_setting(key, value)

def depsOf_of_mirteFile_instance_definition(man, insts):
	""" Returns a function that returns the dependencies of
	    an instance definition by its name, where insts is a
	    dictionary of instance definitions from a mirteFile """
	return lambda x: map(lambda a: a[1],
			     filter(lambda b: b[0] in \
				[d.type for d in 
					man.modules[insts[x]['module']].deps],
				insts[x].items()))

def depsOf_of_mirteFile_module_definition(defs):
	""" Returns a function that returns the dependencies of a module
	    definition by its name, where defs is a dictionary of module
	    definitions from a mirteFile """
	return lambda x: (filter(lambda z: z in defs,
				 map(lambda y: y[1]['type'],
			      	     defs[x]['settings'].items()
				     	if 'settings' in defs[x] else []))) + \
			 (defs[x]['inherits'] if 'inherits' in defs[x] else [])

def module_definition_from_mirteFile_dict(man, d):
	""" Creates a ModuleDefinition instance from the dictionary <d> from
	    a mirte-file for the Manager instance <man>. """
	m = ModuleDefinition()
	if not 'inherits' in d: d['inherits'] = list()
	if not 'settings' in d: d['settings'] = dict()
	if 'implementedBy' in d:
		m.implementedBy = d['implementedBy']
	if 'run' in d and d['run']:
		m.run = True
	m.inherits = set(d['inherits'])
	for p in d['inherits']:
		if not p in man.modules:
			raise ValueError, "No such module %s" % p
		m.deps.update(man.modules[p].deps)
		m.vsettings.update(man.modules[p].vsettings)
		m.inherits.update(man.modules[p].inherits)
		m.run = m.run or man.modules[p].run
	if len(m.inherits) == 0:
		m.inherits = set(['module'])
	for k, v in d['settings'].iteritems():
		if v['type'] in man.modules:
			m.deps[k] = DepDefinition(v['type'])
		elif v['type'] in man.valueTypes:
			m.vsettings[k] = VSettingDefinition(v['type'],
				v['default'] if 'default' in v else None)
		else:
			raise ValueError, \
				"No such module or valuetype %s" % v
	return m

def load_mirteFile(path, m, logger=None):
	""" Loads the mirte-file at <path> into the manager <m>. """
	l = logging.getLogger('load_mirteFile') if logger is None else logger
	for path, d in walk_mirteFiles(path):
		l.info('loading %s' % path)
		_load_mirteFile(d, m)

def _load_mirteFile(d, m):
	""" Loads the dictionary from the mirteFile into <m> """
	defs = d['definitions'] if 'definitions' in d else {}
	insts = d['instances'] if 'instances' in d else {}
	it = sort_by_successors(defs.keys(), dual_cover(defs.keys(),
		restricted_cover(defs.keys(),
				 depsOf_of_mirteFile_module_definition(defs))))
	for k in it:
		m.add_module_definition(k,
			module_definition_from_mirteFile_dict(m, defs[k]))
	it = sort_by_successors(insts.keys(),
		dual_cover(insts.keys(), restricted_cover(insts.keys(),
			depsOf_of_mirteFile_instance_definition(m, insts))))
	for k in it:
		settings = dict(insts[k])
		del(settings['module'])
		m.create_instance(k, insts[k]['module'], settings)

def walk_mirteFiles(path):
	""" Yields (cpath, d) for all dependencies of and including the
	    mirte-file at <path>, where <d> are the dictionaries from
	    the mirte-file at <cpath> """
	stack = [path]
	loadStack = []
	had = dict()
	while stack:
		path = stack.pop()
		if os.path.abspath(path) in had:
			d = had[os.path.abspath(path)]
		else:
			with open(path) as f:
				d = yaml.load(f)
			had[os.path.abspath(path)] = d
		loadStack.append((path, d))
		if not 'includes' in d:
			continue
		for include in d['includes']:
			p = os.path.join(os.path.dirname(path),
						  include)
			stack.append(p)
	had = set()
	for path, d in reversed(loadStack):
		if os.path.abspath(path) in had:
			continue
		had.add(os.path.abspath(path))
		yield path, d

def parse_cmdLine(args):
	""" Parses commandline arguments into options and arguments """
	options = dict()
	rargs = list()
	for arg in args:
		if arg[:2] == '--':
			tmp = arg[2:]
			bits = tmp.split('=', 1)
			if len(bits) == 1:
				bits.append('')
			options[bits[0]] = bits[1]
		else:
			rargs.append(arg)
	return options, rargs

def execute_cmdLine_options(options, m, l):
	""" Applies the instructions given via <options> on the manager <m> """
	opt_lut = dict()
	inst_lut = dict()
	for k, v in options.iteritems():
		bits = k.split('-', 1)
		if len(bits) == 1:
			inst_lut[bits[0]] = v
		else:
			if not bits[0] in opt_lut:
				opt_lut[bits[0]] = list()
			opt_lut[bits[0]].append((bits[1], v))
	inst_list = sort_by_successors(inst_lut.keys(),
			lambda inst: [v for (k,v) in opt_lut.get(inst, ())
					if k in m.modules[inst_lut[inst]].deps])
	for k in reversed(tuple(inst_list)):
		if k in m.insts:
			raise NotImplementedError, \
				"Overwriting instancens not yet supported"
		settings = dict()
		if k in opt_lut:
			for k2, v2 in opt_lut[k]:
				settings[k2] = v2
		m.create_instance(k, inst_lut[k], settings)
	for k in opt_lut:
		if k in inst_lut:
			continue
		for k2, v2 in opt_lut[k]:
			if not k in m.insts:
				raise ValueError, "No such instance %s" % k
			m.change_setting(k, k2, v2)

def main():
	""" Entry-point """
	logging.basicConfig(level=logging.DEBUG,
	    format="%(relativeCreated)d %(levelname)s:%(name)s:%(message)s")
	l = logging.getLogger('mirte')
	options, args = parse_cmdLine(sys.argv[1:])
	m = Manager(l)
	path = args[0] if len(args) > 0 else 'default.mirte'
	load_mirteFile(path, m, logger=l)
	execute_cmdLine_options(options, m, l)
	m.run()

if __name__ == '__main__':
	if os.path.abspath('.') in sys.path:
		sys.path.remove(os.path.abspath('.'))
	main()
