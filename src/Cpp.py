from StringBuilder import StringBuilder
from godot_types import *
import re

# ClassDefinition
# contains the code being generated for a class
# as we need to reorder it a lot
class ClassDefinition:
	def __init__(self, name):
		self.name = name

		self.class_hpp = StringBuilder()
		
		# remember if currently is declaring protected or public members
		# True == protected, False == public
		self.toggle_protected_public = False
		
		# method arguments for bindings (method_name:args[])
		self.method_args = {}
		
		# signal arguments for bindings (signal_name:args{arg_name:type})
		self.signals = {}
		
		# onready assignments, moved to the ready function 
		self.onready_assigns = []

		# static assignments, moved to the end of hpp
		self.static_assigns = []
		
		# annotations (tuple<property_name,annotation_name,params> )
		self.annotations = []
		
		# accesors (member_name:accessors_name)
		self.accessors_get = {}
		self.accessors_set = {}
	
	def protected(self):
		if not self.toggle_protected_public: 
			self.class_hpp += '\nprotected:\n'
			self.toggle_protected_public = True
		return self.class_hpp
	
	def public(self):
		if self.toggle_protected_public: 
			self.class_hpp += '\npublic:\n'
			self.toggle_protected_public = False
		return self.class_hpp

class Transpiler:
	
	def __init__(self, script_name, out_name, vprint):
		
		self.script_name = script_name
		self.out_name = out_name
		
		# verbose printing
		self.vprint = vprint
		
		# scope level
		self.level = 0
		
		# class definitions
		# NOTE: self.klass is the ClassData the parser generated
		# while self.class_definitions are the code we are currently generating
		self.class_definitions = {}
		
		# to generate includes
		self.used_types = set()

		# allows to parse code and rearrange it
		self.layers = [StringBuilder()]
		
		# result hpp
		self.hpp = StringBuilder()
		# result cpp
		self.cpp = StringBuilder()
		
	
	# ClassData (methods and member types, generated by parser)
	# NOTE: helps since classes can be nested
	def current_class(self, class_name, klass):
		self.class_name = class_name
		self.klass = klass
	
	def define_class(self, name, base_class, is_tool, is_main):
		self.used_types.add(base_class)
		self.class_definitions[name] = ClassDefinition(name)
		self.getClass().class_hpp += f'class {name} : public {base_class} {{\n\tGDCLASS({name}, {base_class});\npublic:\n'
	
	def getClass(self):
		return self.class_definitions[self.class_name]
	
	def enum(self, name, params, params_init):
		def_ = ''
		for i, (pName, pType) in enumerate(params.items()):
				if i != 0: def_ += ', '
				def_ += pName
				if pName in params_init:
					self.addLayer(); get(params_init[pName])
					def_ += ' = ' + self.popLayer()
		public = self.getClass().public(); public += f'\tenum {name} {{{def_}}};'
	
	# NOTE: endline is the following space, for prettier output
	def annotation(self, name, params, memberName, endline):
		self.getClass().annotations.append( (memberName, name, params) )
	
	def declare_property(self, type, name, assignment, accessors, constant, static, onready):
		const_decl = 'const ' if constant else 'static ' if static else ''
		protected = self.getClass().protected()
		protected += f'\t{const_decl}{self.translate_type(type)} {name}'
		if assignment:
			self.addLayer()
			if onready:
				self += name; self.assignment(assignment)
				self.getClass().onready_assigns.append(self.popLayer())
			elif static:
				self += f'{type} {self.class_name}::{name}'; self.assignment(assignment)
				self.getClass().static_assigns.append(self.popLayer())
			else:
				self.assignment(assignment); protected += self.popLayer()
		protected += ';'

		# setget
		if accessors:
			# call the appropriate Transpiler method (defined afterward)
			set_defined = False
			get_defined = False
			for accessor in accessors:
				method_name = accessor[0]
				set_defined = set_defined or method_name.startswith('set')
				get_defined = get_defined or method_name.startswith('get')
				method = getattr(self,method_name)
				params = accessor[1:]
				method(name, *params)
			if set_defined and not get_defined: self.addDefaultGet(name)
			if get_defined and not set_defined: self.addDefaultSet(name)

	def getter_method(self, member, getterName):
		self.getClass().accessors_get[member] = getterName
	
	def setter_method(self, member, setterName):
		self.getClass().accessors_set[member] = setterName
	
	def getter(self, member, code):
		self.getClass().accessors_get[member] = toGet(member)
		self.define_method(toGet(member), code = code, return_type = self.klass.members[member])
	
	def setter(self, member, valueName, code):
		self.getClass().accessors_set[member] = toSet(member)
		self.define_method(toSet(member), code = code, params = {valueName:self.klass.members[member]})
	
	def declare_variable(self, type, name, assignment):
		self += f'{self.translate_type(type)} {name}'
		if assignment: self.assignment(assignment)
	
	def define_method(self, name, params = {}, params_init = {}, return_type = None, code = '', static = False, override = False):

		# for method bindings
		self.getClass().method_args[name] = params.keys()
		# some methods (notably accesors) need to be registered here for bindings to be generated
		self.klass.methods[name] = return_type
		
		# handle empty function
		if not code: self.addLayer(); self += '\n{\n}'; code = self.popLayer()
		
		# generate param string
		def paramStr(with_init : bool):
			def_ = ''
			for i, (pName, pType) in enumerate(params.items()):
				if i != 0: def_ += ', '
				def_ += f'{self.translate_type(pType)} {pName}'
				if with_init and pName in params_init:
					self.addLayer(); get(params_init[pName])
					def_ += ' = ' + self.popLayer()
			return def_
		
		static_str = 'static ' if static else ''
		override_str = ' override' if override else ''
		public = self.getClass().public()
		public += f'\t{static_str}{self.translate_type(return_type)} {name}({paramStr(True)}){override_str};\n' # hpp
		self += f'{self.translate_type(return_type)} {self.class_name}::{name}({paramStr(False)})' # cpp
		
		# add onready assignments if method is _ready
		if name == '_ready' and self.getClass().onready_assigns:
			onreadies = self.getClass().onready_assigns
			tabs = '\t' * (self.level +1)
			onreadies_code = '{' + ''.join(map(lambda stmt: f'\n{tabs}{stmt};', onreadies))
			code = code.replace('{', onreadies_code, 1)
			self.getClass().onready_assigns.clear()
		
		self.write(code)
	
	def define_signal(self, name, params):
		self.getClass().signals[name] = params
		paramStr = ', '.join( ( f'{self.translate_type(pType)} {pName}' for pName, pType in params.items()))
		hpp = self.getClass().class_hpp
		hpp += f'\t/* signal {name}({paramStr}) */'
	
	def assignment(self, exp):
		self += ' = '; get(exp)
	
	def subexpression(self, expression):
		self += '('; get(expression); self += ')'
	
	def create_array(self, values):
		self += ' /* no array initializer in c++ ! */ {'; self.level += 1
		self += values
		self += '}'; self.level -= 1

	def array_item(self, item):
		get(item); self += ', '
		
	def create_dict(self, values):
		self += ' /* no dictionary initializer in c++ ! */ {'; self.level += 1
		self += values
		self += '}'; self.level -= 1

	def dict_item(self, key, value):
		self += '{'; get(key); self += ', '; get(value); self += '},'
	
	def create_lambda(self, params, code):
		self += '[]('
		for i, (pName, pType) in enumerate(params.items()):
			if i != 0: self += ', '
			self += f'{self.translate_type(pType)} {pName}'
		self += ') '
		# cleanup
		code = code.replace('{', '{\t', 1)
		code = replaceClosingBrace(code, '};' )
		self.write(code)
	
	def literal(self, value):
		if isinstance(value, str):
			# add quotes / escape the quotes inside if necessary
			value = value.replace('\n', '\\\n').replace('"', '\\"')
			value = f'"{value}"'

		elif isinstance(value, bool):
			value = str(value).lower()
		
		self.write(str(value))
	
	def constant(self, name):
		self +=  '::' + name
	
	def property(self, name):
		self += name
	
	def variable(self, name):
		self += variable_replacements.get(name) or name
	
	def singleton(self, name):
		self += name

	def reference(self, name, obj_type, member_type, is_singleton = False):
		use_get = self._dereference(name, obj_type, member_type, is_singleton)
		self += f'{toGet(name)}()' if use_get else name

	def reassignment(self, name, obj_type, member_type, is_singleton, op, val):
		use_set = self._dereference(name, obj_type, member_type, is_singleton)
		op_comment = f' /* {toGet(name)}() */ ' + op.replace('=', '') + ' ' if op != '=' else '' 
		if use_set: self += f'{toSet(name)}(' + op_comment; get(val); self += f')'
		else:  self += f'{name} {op} '; get(val)

	def _dereference(self, name, obj_type, member_type, is_singleton):
		self +=  '::get_singleton()->' if is_singleton \
			else '->' if is_pointer(obj_type) \
			else  '.'
		return name and member_type and not member_type.startswith('signal') and is_pointer(obj_type)
	
	def call(self, name, params, global_function = False):
		if global_function: name = function_replacements.get(name, name)
		self += name + '('
		for i, p in enumerate(params):
			if i>0: self += ', '
			get(p)
		self += ')'
	
	def constructor(self, name, type, params):
		if is_pointer(type): self += 'new '
		self.call(name, params)
	
	def subscription(self, key):
		self+= '['; get(key); self += ']'
		
	def operator(self, op):
		op = '&&' if op == 'and' \
			else '||' if op == 'or' \
			else '!' if op == 'not' \
			else op
		if op == '!': self += op
		else: self += f' {op} '
	
	def ternary(self, iterator):
		# condition, valueIfTrue, valueIfFalse
		self += '( '
		get(iterator); self += ' ? ';
		get(iterator); self += ' : '; get(iterator);
		self += ' )'
	
	def returnStmt(self, return_exp):
		self += 'return '; get(return_exp)
	
	def ifStmt(self, condition):
		self += 'if('; get(condition); self += ')'
	
	def elifStmt(self, condition):
		self += 'else if('; get(condition); self += ')'
	
	def elseStmt(self):
		self += 'else'
	
	def whileStmt(self, condition):
		self += 'while('; get(condition); self += ')'
		
	def forStmt(self, name, type, exp):
		# no custom range operator in c++ afaik
		self.addLayer(); get(exp); iterator = self.popLayer()
		if iterator.startswith('range'):
			iterator = iterator.replace('range(', '', 1)[:-1]
			# just splitting by ',' would allow some bugs
			# ex: 'i in range(func(j,k))'' => 'for(int i=func(j; i<k); i+=1)''
			params = splitArgs(iterator)
			start = params[0].strip() if len(params)>1 else 0
			end = params[0].strip() if len(params)==1 else params[1]
			step = params[2].strip() if len(params)==3 else 1
			# NOTE: will generate '+= -' for negative step ; acceptable to me
			self += f'for({self.translate_type(type)} {name}={start}; {name}<{end}; {name}+={step})'
		else:
			self += f'for({self.translate_type(type)} {name} : {iterator})'
	
	def breakStmt(self): self += 'break;'
	
	def continueStmt(self): self += 'continue;'
	
	def awaitStmt(self, object, signalName):
		object = object.replace('self', 'this')
		signalName = rReplace(rReplace(signalName, 'get_', '', 1), '()', '', 1)
		self += f'/* await {object}->{signalName}; */ // no equivalent to await in c++ !'
	
	def emitSignal(self, name, params):
		self += f'emit_signal("{name}"'
		for i, p in enumerate(params):
			self += ', '
			get(p)
		self += ')'
	
	def connectSignal(self, name, params):
		self += f'connect("{name}", '; get(params[0]); self += ')'
	
	def matchStmt(self, evaluated, cases):
		type = get(evaluated)

		# use switch on literals
		if type in ('int', 'string', 'float'):
			
			self += 'switch('; get(evaluated); self += ')'
			self.UpScope()
			
			for pattern, when, code in cases():
				if pattern == 'default':
					self += 'default:'
				else:
					self += 'case '; get(pattern); self += ':'
					if when: self += ' if('; get(when); self += ')'
				code = replaceClosingBrace(code, '\tbreak; }')
				self.write(code)
		
		 # default to if else chains for objects
		else:
			self.addLayer()
			self += 'if('
			get(evaluated)
			self += ' == '
			comparison = self.popLayer()
			
			for pattern, when, code in cases():
				if pattern == 'default':
					self += 'else '
				else:
					self.write(comparison)
					get(pattern)
					if when: self += ' && '; get(when)
					self += ')'
				self.write(code)
	
	def end_class(self, name):
		# add ready function if there are onready_assigns remaining
		# NOTE : we can end up with 2 _ready functions in generated code
		# we could fix this by accumulating onreadies (and _ready definition if exists)
		# then appending it at the end on script
		# (or replacing a dummy string ex:__READY__ if _ready was defined by user)
		if self.getClass().onready_assigns: self.define_method('_ready', override=True)
		
		# bindings -> _bind_methods() static function
		if self.getClass().annotations or self.klass.methods or self.getClass().signals:
			# NOTE: we generate property bindings first so we can generate missing get set methods,
			# but into a buffer since they need to be declared after method bindings
			bindings = StringBuilder()
			property_bindings = StringBuilder()
			
			bindings += ' {\n'
			for prop, an_name, an_args in self.getClass().annotations:
				if prop: # @export_... property
					type = self.klass.members[prop]
					if not type.startswith('signal'):
						an_name = export_replacements.get(an_name) or an_name.upper()
						
						property_bindings += f'\tClassDB::add_property(get_class_static(), PropertyInfo({toVariantTypeEnum(type)}, "{prop}"'
						
						# PROPERTY_HINT_*****, "args"
						if an_name != 'EXPORT': property_bindings += f', {an_name}, "{an_args}"'
						
						# NOTE: the way setget are handled, if one is missing both are
						# doing it this way to avoid problems if this changes
						accessor_get = self.getClass().accessors_get.get(prop)
						accessor_set = self.getClass().accessors_set.get(prop)
						
						# add accessors to binding
						property_bindings += f'), "{accessor_set or toSet(prop)}", "{accessor_get or toGet(prop)}");\n'
						
						# define accessors if missing
						if not accessor_set: self.addDefaultSet(prop)
						if not accessor_get: self.addDefaultGet(prop)
				
				else: # @export_group, subgroup, category
					an_name = an_name.replace('export_','')
					property_bindings += f'\tClassDB::add_property_{an_name}(get_class_static(), "{an_args}","");\n'
			
			# signals
			for signal, args in self.getClass().signals.items():
				params = ', '.join(map(lambda item: f'PropertyInfo({toVariantTypeEnum(item[1])}, "{item[0]}")', args.items()))
				params = ', ' +params if params else params 
				property_bindings += f'\tClassDB::add_signal(get_class_static(), MethodInfo("{signal}"{params}));\n'
			
			# methods
			for meth, type in self.klass.methods.items():
				if not meth.startswith('_'): # _method => not exported
					params = ', '.join(map(lambda s: f'"{s}"', self.getClass().method_args[meth]))
					params = ', ' + params if params else params
					bindings += f'\tClassDB::bind_method(D_METHOD("{meth}"{params}), &{self.class_name}::{meth});\n'

			# enums
			bindings += '\n'.join( f'\tClassDB::bind_integer_constant(get_class_static(), _gde_constant_get_enum_name({name}, "{name}"), "{name}", {name});' \
				for name in self.klass.enums.keys() )
			
			bindings += '\n'
			
			# property bindings go after method bindings
			bindings += property_bindings
			
			# close bindings method
			bindings += '}\n'
			
			pb = self.getClass().public(); pb += '\n'; self += '\n'
			self.define_method('_bind_methods', code = str(bindings), static = True)
		
		# add class definition + close it
		self.hpp += self.getClass().class_hpp
		self.hpp += '};\n\n'

		# add static assignment
		for sass in self.getClass().static_assigns:
			self.cpp += f'{sass};\n'

		# add enum binding after class binding (if any)
		if self.klass.enums:
			self.hpp += '\n'.join( f'VARIANT_ENUM_CAST({self.getClass().name}::{self.translate_type(enum_name)})'  \
				for enum_name in sorted(set(self.klass.enums.values())) if self.translate_type(enum_name))
	
	def end_script(self):
		self.end_class(self.class_name)
		
		# close remaining scopes (notably script-level class)
		while len(self.layers) > 1: self.write(self.popLayer())
		while self.level > 0: self.DownScope()

		# generate includes
		to_camel_case = lambda s: re.sub(r'(?<!^)(?=[A-Z])', '_', s).lower()
		to_include = lambda s: '#include <godot_cpp/classes/' \
			+ to_camel_case(s) \
			.replace('2_d', '2d') \
			.replace('3_d', '3d') \
			+ '.hpp>'
		includes =  '\n'.join(map(to_include, sorted(self.used_types))) + '\n'

		self.cpp = prettify( cpp_template \
			.replace('__HEADER__', self.script_name) \
			+ str(self.getLayer()).replace('\n}', '\n}\n\n') \
			)
		self.hpp = prettify( hpp_template \
			.replace('__CLASS__', self.script_name.upper()) \
			.replace('__INCLUDES__', includes) \
			.replace('__IMPLEMENTATION__', str(self.hpp)) \
			)

	def addDefaultSet(self, prop_name):
		self.getClass().accessors_set[prop_name] = toSet(prop_name)
		self.setter(prop_name, 'value', f' {{\n\t{prop_name} = value;\n}}\n')
	def addDefaultGet(self, prop_name):
		self.getClass().accessors_get[prop_name] = toGet(prop_name)
		self.getter(prop_name, f' {{\n\treturn {prop_name};\n}}\n')

	def translate_type(self, type):
		if type == None: return 'void'
		if type == 'Variant': return type
		if type == 'string': return 'String'
		if type.endswith('[]'): return 'Array'
		if type.endswith('enum'): return type[:-len('enum')].replace('.', '::')
		if type == 'float' and not use_floats: return 'double'
		if toVariantTypeConstant(type): return type

		# to generate includes
		if type in godot_types: self.used_types.add(type)

		return f'Ref<{type}>'
	
	def comment(self, content):
		handler = self.getWhitespaceHandler()
		handler += f"//{content}"
	
	def multiline_comment(self, content):
		handler = self.getWhitespaceHandler()
		handler += f"/*{content}*/"
	
	def getWhitespaceHandler(self):
		return self if self.level > 0 \
			else self.getClass().class_hpp if self.class_definitions \
			else self.hpp
	
	def end_statement(self):
		if self.level > 0: self += ';'
	
	""" code generation utils """
	
	# += operator override to generate code
	def __iadd__(self, txt):
		endline_only = all( ( c=='\n' for c in txt ) )
		handler = self.getWhitespaceHandler() if endline_only else self
		
		# automatic indentation
		if '\n' in txt: txt = txt.replace('\n', '\n' + '\t' * self.level)
		handler.write(txt)

		self.vprint("emit:", txt.replace("\n", "<EOL>").replace('\t', '  '))
		return self
	
	def write(self, txt):
		self.getLayer().write(txt)
	
	def get_result(self):
		return (self.hpp, self.cpp)
	
	def save_result(self):
		
		self.out_name = self.out_name.replace('.cpp', '').replace('.hpp', ''):
		
		cpp_outname = self.out_name += '.cpp'
		hpp_out_name = self.out_name += '.hpp'
		
		result = self.get_result()

		os.makedirs(os.path.dirname(hpp_out_name), exist_ok=True)
		with open(hpp_out_name,'w+') as wf:
			wf.write(result[0])
		
		os.makedirs(os.path.dirname(cpp_outname), exist_ok=True)
		with open(cpp_outname,'w+') as wf:
			wf.write(result[1])
	
	def UpScope(self):
		self.vprint('UpScope', self.level)
		self += '\n{'
		self.level += 1
	
	def DownScope(self):
		self.vprint('DownScope', self.level)
		if self.level != 0:
			self.level -= 1
			self += '\n}'
	
	# layers : used for method definition
	# so we can parse return type then add code
	
	def getLayer(self):
		return self.layers[-1]
	
	def addLayer(self):
		self.layers.append(StringBuilder())
		
	def popLayer(self):
		# add top scope txt to lower then remove top
		scope = str(self.layers[-1])
		self.layers.pop()
		return scope

def rReplace(string, toReplace, newValue, n = 1): return newValue.join(string.rsplit(toReplace,n))

def replaceClosingBrace(string, replacement):
	def impl():
		open_brackets = 0
		for c in string:
			if c == '{': open_brackets += 1
			elif c == '}':
				open_brackets -= 1
				if open_brackets == 0:
					yield replacement
					# ensure it triggers only once
					open_brackets = 999
					continue
			yield c
	return ''.join(impl())

def splitArgs(string):
	def impl():
		open_parenthesis = 0
		start = 0
		for i, c in enumerate(string):
			if c == '(': open_parenthesis += 1
			elif c == ')':
				open_parenthesis -= 1
			elif c == ',' and open_parenthesis == 0:
				yield string[start:i]
				start = i+1
		yield string[start:]
	return [ item for item in impl()]

def toSet(name): return f'set_{name}'
def toGet(name): return f'get_{name}'

def is_pointer(type): return type and not toVariantTypeConstant(type)

def toVariantTypeConstant(type):
	# NOTE: binding enums as int ; that's the standards afaik
	# see https://github.com/godotengine/godot/issues/15922
	if   type.endswith('enum'): type = 'int'
	elif type.endswith('[]'): type = 'Array'

	match = (vt for vt in variant_types if vt.replace('TYPE_', '', 1).replace('_','') == type.upper())
	return next(match, None)

def toVariantTypeEnum(type):
	translated = toVariantTypeConstant(type)
	return 'Variant::' + (translated.replace('TYPE_', '', 1) if translated else 'OBJECT')

# for prettier output
def prettify(value):
	def impl():
		cnt = 0
		line = ''
		for c in value:
			if c == '\n':
				line = ''
				cnt += 1
				if cnt < 3: yield c
			elif cnt > 0 and c == ';':  pass
			elif cnt > 0 and c == ' ':  line += c
			elif cnt > 0 and c == '\t': line += c
			else: cnt = 0; yield line + c; line = ''
	return ''.join(impl())

# trick for generator values
get = next

hpp_template = """
#ifndef __CLASS___H
#define __CLASS___H

#include <godot_cpp/godot.hpp>
#include <godot_cpp/variant/array.hpp>
#include <godot_cpp/variant/dictionary.hpp>
__INCLUDES__

using namespace godot;

__IMPLEMENTATION__

#endif // __CLASS___H
"""

cpp_template = """
#include "__HEADER__.hpp"

#include <godot_cpp/core/object.hpp>
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/variant/utility_functions.hpp>


"""

export_replacements = {
	'export_range':'PROPERTY_HINT_RANGE',
	'export_enum':'PROPERTY_HINT_ENUM',
	'export_enum_suggestion':'PROPERTY_HINT_ENUM_SUGGESTION',
	'export_exp_easing':'PROPERTY_HINT_EXP_EASING',
	'export_link':'PROPERTY_HINT_LINK',
	'export_flags':'PROPERTY_HINT_FLAGS',
	'export_layers_2d_render':'PROPERTY_HINT_LAYERS_2D_RENDER',
	'export_layers_2d_physics':'PROPERTY_HINT_LAYERS_2D_PHYSICS',
	'export_layers_2d_navigation':'PROPERTY_HINT_LAYERS_2D_NAVIGATION',
	'export_layers_3d_render':'PROPERTY_HINT_LAYERS_3D_RENDER',
	'export_layers_3d_physics':'PROPERTY_HINT_LAYERS_3D_PHYSICS',
	'export_layers_3d_navigation':'PROPERTY_HINT_LAYERS_3D_NAVIGATION',
	'export_layers_avoidance':'PROPERTY_HINT_LAYERS_AVOIDANCE',
	'export_file':'PROPERTY_HINT_FILE',
	'export_dir':'PROPERTY_HINT_DIR',
	'export_global_file':'PROPERTY_HINT_GLOBAL_FILE',
	'export_global_dir':'PROPERTY_HINT_GLOBAL_DIR',
	'export_resource_type':'PROPERTY_HINT_RESOURCE_TYPE',
	'export_multiline_text':'PROPERTY_HINT_MULTILINE_TEXT',
	'export_expression':'PROPERTY_HINT_EXPRESSION',
	'export_placeholder_text':'PROPERTY_HINT_PLACEHOLDER_TEXT',
	'export_color_no_alpha':'PROPERTY_HINT_COLOR_NO_ALPHA',
	'export_object_id':'PROPERTY_HINT_OBJECT_ID',
	'export_type_string':'PROPERTY_HINT_TYPE_STRING',
	'export_node_path_to_edited_nod':'PROPERTY_HINT_NODE_PATH_TO_EDITED_NODE',
	'export_object_too_big':'PROPERTY_HINT_OBJECT_TOO_BIG',
	'export_node_path_valid_types':'PROPERTY_HINT_NODE_PATH_VALID_TYPES',
	'export_save_file':'PROPERTY_HINT_SAVE_FILE',
	'export_global_save_file':'PROPERTY_HINT_GLOBAL_SAVE_FILE',
	'export_int_is_objectid':'PROPERTY_HINT_INT_IS_OBJECTID',
	'export_int_is_pointer':'PROPERTY_HINT_INT_IS_POINTER',
	'export_array_type':'PROPERTY_HINT_ARRAY_TYPE',
	'export_locale_id':'PROPERTY_HINT_LOCALE_ID',
	'export_localizable_string':'PROPERTY_HINT_LOCALIZABLE_STRING',
	'export_node_type':'PROPERTY_HINT_NODE_TYPE',
	'export_hide_quaternion_edit':'PROPERTY_HINT_HIDE_QUATERNION_EDIT',
	'export_password':'PROPERTY_HINT_PASSWORD',
}

variable_replacements = {
	"self":"this",
	"PI":"Math::Pi",
	"TAU":"Math::Tau",
	"INF":"Math::Inf",
	"NAN":"Math::NaN",
}

function_replacements = {
	'preload': "/* preload has no equivalent, add a 'ResourcePreloader' Node in your scene */",
	'weakref': 'UtilityFunctions::weakref(obj)',
	'instance_from_id' : 'UtilityFunctions::instance_from_id',
	'is_instance_id_valid' : 'UtilityFunctions::is_instance_id_valid',
	'is_instance_valid' : 'UtilityFunctions::is_instance_valid',
	'abs' : 'Math::abs',
	'absf' : 'Math::abs',
	'absi' : 'Math::abs',
	'acos' : 'Math::acos',
	'acosh' : 'Math::acosh',
	'angle_difference' : 'Math::angle_difference',
	'asin' : 'Math::asin',
	'asinh' : 'Math::asinh',
	'atan' : 'Math::atan',
	'atan2' : 'Math::atan2',
	'atanh' : 'Math::atanh',
	'bezier_derivative' : 'Math::bezier_derivative',
	'bezier_interpolate' : 'Math::bezier_interpolate',
	'bytes_to_var' : 'UtilityFunctions::bytes_to_var',
	'bytes_to_var_with_objects' : 'UtilityFunctions::bytes_to_var_with_objects',
	'ceil' : 'Math::ceil',
	'ceilf' : 'Math::ceil',
	'ceili' : 'Math::ceil_to_int',
	'clamp' : 'Math::clamp',
	'clampf' : 'Math::clamp',
	'clampi' : 'Math::clamp',
	'cos' : 'Math::cos',
	'cosh' : 'Math::cosh',
	'cubic_interpolate' : 'Math::cubic_interpolate',
	'cubic_interpolate_angle' : 'Math::cubic_interpolate_angle',
	'cubic_interpolate_angle_in_time' : 'Math::cubic_interpolate_in_time',
	'cubic_interpolate_in_time' : 'Math::cubic_interpolate_angle_in_time',
	'db_to_linear' : 'Math::db_to_linear',
	'deg_to_rad' : 'Math::deg_to_rad',
	'ease' : 'Math::ease',
	'error_string' : 'Error::to_string',
	'exp' : 'Math::exp',
	'floor' : 'Math::floor',
	'floorf' : 'Math::floor',
	'floori' : 'Math::floor_to_int',
	'fmod' : 'Math::mod',
	'fposmod' : 'Math::pos_mod',
	'hash' : 'UtilityFunctions::hash',
	'inverse_lerp' : 'Math::inverse_lerp',
	'is_equal_approx' : 'Math::is_equal_approx',
	'is_finite' : 'Math::is_finite',
	'is_inf' : 'Math::is_inf',
	'is_nan' : 'double::is_na_n',
	'is_same' : 'ReferenceEquals::reference_equals',
	'is_zero_approx' : 'Math::is_zero_approx',
	'lerp' : 'Math::lerp',
	'lerp_angle' : 'Math::lerp_angle',
	'lerpf' : 'Math::lerp',
	'linear_to_db' : 'Math::linear_to_db',
	'log' : 'Math::log',
	'max' : 'Math::max',
	'maxf' : 'Math::max',
	'maxi' : 'Math::max',
	'min' : 'Math::min',
	'minf' : 'Math::min',
	'mini' : 'Math::min',
	'move_toward' : 'Math::move_toward',
	'nearest_po2' : 'Math::nearest_po2',
	'pingpong' : 'Math::ping_pong',
	'posmod' : 'Math::pos_mod',
	'pow' : 'Math::pow',
	'print' : 'UtilityFunctions::print',
	'print_rich' : 'UtilityFunctions::print_rich',
	'printerr' : 'UtilityFunctions::print_err',
	'printraw' : 'UtilityFunctions::print_raw',
	'prints' : 'UtilityFunctions::print_s',
	'printt' : 'UtilityFunctions::print_t',
	'push_error' : 'UtilityFunctions::push_error',
	'push_warning' : 'UtilityFunctions::push_warning',
	'rad_to_deg' : 'Math::rad_to_deg',
	'rand_from_seed' : 'UtilityFunctions::rand_from_seed',
	'randf' : 'UtilityFunctions::randf',
	'randf_range' : 'UtilityFunctions::rand_range',
	'randfn' : 'UtilityFunctions::randfn',
	'randi' : 'UtilityFunctions::randi',
	'randi_range' : 'UtilityFunctions::rand_range',
	'randomize' : 'UtilityFunctions::randomize',
	'remap' : 'Math::remap',
	'rotate_toward' : 'Math::rotate_toward',
	'round' : 'Math::round',
	'roundf' : 'Math::round',
	'roundi' : 'Math::round_to_int',
	'seed' : 'UtilityFunctions::seed',
	'sign' : 'Math::sign',
	'signf' : 'Math::sign',
	'signi' : 'Math::sign',
	'sin' : 'Math::sin',
	'sinh' : 'Math::sinh',
	'smoothstep' : 'Math::smooth_step',
	'snapped' : 'Math::snapped',
	'snappedf' : 'Math::snapped',
	'snappedi' : 'Math::snapped',
	'sqrt' : 'Math::sqrt',
	'step_decimals' : 'Math::step_decimals',
	'str_to_var' : 'UtilityFunctions::str_to_var',
	'tan' : 'Math::tan',
	'tanh' : 'Math::tanh',
	'type_convert' : 'UtilityFunctions::convert',
	'type_string' : 'Variant::to_string',
	'typeof' : 'Variant::variant_type',
	'var_to_bytes' : 'UtilityFunctions::var_to_bytes',
	'var_to_bytes_with_objects' : 'UtilityFunctions::var_to_bytes_with_objects',
	'var_to_str' : 'UtilityFunctions::var_to_str',
	'wrap' : 'Math::wrap',
	'wrapf' : 'Math::wrap',
	'wrapi' : 'Math::wrap',
}