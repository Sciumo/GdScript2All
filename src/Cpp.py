from StringBuilder import StringBuilder
from godot_types import godot_types

# ClassDefinition
# contains the code being generated for a class
# as we need to reorder it a lot
class ClassDefinition:
	def __init__(self):
		self.class_hpp = StringBuilder()
		
		# remember if currently is declaring protected or public members
		# True == protected, False == public
		self.toggle_protected_public = False
		
		# method arguments for bindings (method_name:args[])
		self.method_args = {}
		
		# signal arguments for bindings (signal_name:args{arg_name:type})
		self.signals = {}
		
		# onready assignments
		# they are moved moved to the ready function of the corresponding class
		self.onready_assigns = []
		
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
	
	def __init__(self, vprint):
		
		# verbose printing
		self.vprint = vprint
		
		# scope level
		self.level = 0
		
		# class definitions
		# NOTE: self.klass is the ClassData the parser generated
		# while self.class_definitions are the code we are currently generating
		self.class_definitions = {}
		
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
	
	def define_class(self, name, base_class, is_tool):
		self.class_definitions[name] = ClassDefinition()
		self.getClass().class_hpp += f'class {name} : public {base_class} {{\n\tGDCLASS({name}, {base_class});\npublic:\n'
	
	def getClass(self):
		return self.class_definitions[self.class_name]
	
	# NOTE: enums have similar syntax in gdscript, C# and cpp
	# lazily passing the enum definition as-is for now
	def enum(self, name, definition):
		public = self.getClass().public(); public += f'\tenum {name} {definition};'
	
	# NOTE: endline is the following space, for prettier output
	def annotation(self, name, params, memberName, endline):
		self.getClass().annotations.append( (memberName, name, params) )
	
	def declare_property(self, type, name, assignment, constant, static):
		type = translate_type(type)
		if assignment: 
			self.addLayer()
			get(assignment)
			assignment = self.popLayer()
		else: assignment = ''
		const_decl = 'const ' if constant else 'static ' if static else ''
		protected = self.getClass().protected()
		protected += f'\t{const_decl}{type} {name}' + assignment + ';'
	
	def setget(self, member, accessors):
		# call the appropriate Transpiler method (defined afterward)
		for accessor in accessors:
			method_name = accessor[0]
			method = getattr(self,method_name)
			params = accessor[1:]
			method(member, *params)
		
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
		self += f'{type} {name}'
		if assignment: get(assignment)
	
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
				def_ += f'{translate_type(pType)} {pName}'
				if with_init and pName in params_init:
					self.addLayer(); get(params_init[pName])
					def_ += ' = ' + self.popLayer()
			return def_
		
		static_str = 'static ' if static else ''
		override_str = ' override' if override else ''
		public = self.getClass().public()
		public += f'\t{static_str}{translate_type(return_type)} {name}({paramStr(True)}){override_str};\n' # hpp
		self += f'{static_str}{translate_type(return_type)} {self.class_name}::{name}({paramStr(False)})' # cpp
		
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
		paramStr = ', '.join( ( f'{translate_type(pType)} {pName}' for pName, pType in params.items()))
		hpp = self.getClass().class_hpp
		hpp += f'\t/* signal {name}({paramStr}) */'
	
	def assignment(self, exp, onreadyName):
		if onreadyName:
			self.addLayer()
			self.write(f'{onreadyName} = '); get(exp)
			self.getClass().onready_assigns.append(self.popLayer())
			return
		self += ' = '; get(exp)
	
	def subexpression(self, expression):
		self += '('; get(expression); self += ')'
	
	def create_array(self, values):
		self += 'new Array{'; self.level += 1
		for value in values:
			get(value); self += ','
		self += '}'; self.level -= 1
		
	def create_dict(self, kv):
		self += 'new Dictionary{'; self.level += 1
		for key, value in kv:
			self += '{'; get(key); self += ','; get(value); self+= '},'
		self += '}'; self.level -= 1
	
	def create_dict(self, kv):
		self += 'new Dictionary{'; self.level += 1
		for key, value in kv:
			self += '{'; get(key); self += ','; get(value); self+= '},'
		self += '}'; self.level -= 1
	
	def create_lambda(self, params, code):
		self += '('
		for i, (pName, pType) in enumerate(params.items()):
			if i != 0: self += ', '
			self += f'{translate_type(pType)} {pName}'
		self += ') =>'
		# cleanup
		code = code.replace('{', '{\t', 1)
		code = rReplace(code, '}', '};')
		self.write(code)
	
	def literal(self, value):
		# strings
		if isinstance(value, str):
			# add quotes / escape the quotes inside if necessary
			value = value.replace('\n', '\\\n').replace('"', '\\"')
			value = f'"{value}"'
		
		# booleans
		elif isinstance(value, bool):
			self += str(value).lower(); return
		
		self += str(value)
	
	def constant(self, name):
		self += '::' + name
	
	def this(self):
		self += 'this->'
	
	def property(self, name):
		self += name
	
	def variable(self, name):
		self += name
	
	def singleton(self, name):
		self += name
	
	def reference(self, name):
		self += '.' + name
	
	def call(self, name, params, global_function = False):
		if global_function: name = function_replacements.get(name, name)
		self += name + '('
		for i, p in enumerate(params):
			if i>0: self += ', '
			get(p)
		self += ')'
	
	def constructor(self, name, params):
		self += 'new '; self.call(name, params)
	
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
		self += f'for({type} {name} : '; get(exp); self += ')'
	
	def breakStmt(self): self += 'break;'
	
	def continueStmt(self): self += 'continue;'
	
	def awaitStmt(self, object, signalName):
		self += f'/* await {object}.{signalName}; */ // no equivalent to await in c++ !'
	
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
			
			for pattern, when in cases(True):
				if pattern == 'default':
					self += 'default:'
				else:
					self += 'case '; get(pattern); self += ':'
					if when: self += ' if('; get(when); self += ')'
		
		 # default to if else chains for objects
		else:
			self.addLayer()
			self += 'if('
			get(evaluated)
			self += ' == '
			comparison = self.popLayer()
			
			for pattern, when in cases():
				if pattern == 'default':
					self += 'else '
				else:
					self.write(comparison)
					get(pattern)
					if when: self += ' && '; get(when)
					self += ')'
	
	def end_class(self, name):
		# add ready function if there are onready_assigns remaining
		# NOTE : we can end up with 2 _ready functions in generated code
		# we could fix this by accumulating onreadies (and _ready definition if exists)
		# then appending it at the end on script
		# (or replacing a dummy string ex:__READY__ if _ready was defined by user)
		if self.getClass().onready_assigns: self.define_method('_ready', override=True)
		
		# bindings ( _bind_methods() static function )
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
					
					property_bindings += f'\tADD_PROPERTY(PropertyInfo({type_enum(type)}, "{prop}"'
					
					# PROPERTY_HINT_*****, "args"
					if an_name != 'EXPORT': property_bindings += f', {an_name}, "{an_args}"'
					
					accessor_get = self.getClass().accessors_get.get(prop)
					accessor_set = self.getClass().accessors_set.get(prop)
					
					# add accessors to binding
					property_bindings += f'), "{accessor_set or toSet(prop)}", "{accessor_get or toGet(prop)}");\n'
					
					# define accessors if missing
					if not accessor_get: self.setter(prop, 'value', f' {{\n\t{prop} = value;\n}}\n')
					if not accessor_get: self.getter(prop, f' {{\n\treturn {prop};\n}}\n')
			
			else: # @export_group, subgroup, category
				an_name = an_name.replace('export_','').upper()
				property_bindings += f'\tADD_{an_name}("{an_args}","");\n'
		
		# signals
		for signal, args in self.getClass().signals.items():
			params = ', '.join(map(lambda item: f'PropertyInfo({type_enum(item[1])}, "{item[0]}")', args.items()))
			params = ', ' +params if params else params 
			property_bindings += f'\tADD_SIGNAL(MethodInfo("{signal}"{params}));\n'
		
		# methods
		for meth, type in self.klass.methods.items():
			if not meth.startswith('_'): # _method => not exported
				params = ', '.join(map(lambda s: f'"{s}"', self.getClass().method_args[meth]))
				params = ', ' + params if params else params
				bindings += f'\tClassDB::bind_method(D_METHOD("{meth}"{params}), &{self.class_name}::{meth});\n'
		
		bindings += '\n'
		
		# property bindings go after method bindings
		bindings += property_bindings
		
		# close bindings method
		bindings += '}\n'
		
		pb = self.getClass().public(); pb += '\n'
		self.define_method('_bind_methods', code = str(bindings), static = True)
		
		#print('ending_class', name)
		#if name.startswith('Nested'):
		#	print('------------------------')
		#	print(self.getClass().class_hpp)
		
		# add class definition + close it
		self.hpp += self.getClass().class_hpp
		self.hpp += '}\n\n'
	
	def end_script(self):
		self.end_class(self.class_name)
		
		# close remaining scopes (notably script-level class)
		while len(self.layers) > 1: self.write(self.popLayer())
		while self.level > 0: self.DownScope()
		
		# NOTE: class_name is not necessarily the name of the hpp file !
		self.cpp = prettify(f'#include "{self.class_name}.hpp"\n' \
			+ '#include <godot_cpp/core/class_db.hpp>\n\n\n' \
			+ str(self.getLayer()).replace('\n}', '\n}\n\n') \
			)
		self.hpp = prettify( hpp_template \
			.replace('__CLASS__', self.class_name.upper()) \
			.replace('__IMPLEMENTATION__', \
				str(self.hpp)) \
			)
	
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

		self.vprint(">", txt.replace("\n", "<EOL>").replace('\t', '  '))
		return self
	
	def write(self, txt):
		self.getLayer().write(txt)
	
	def get_result(self):
		return (self.hpp, self.cpp)
	
	def save_result(self, outname):
		if not outname.endswith('.cpp'): outname += '.cpp'
		
		result = self.get_result()
		
		with open(outname.replace('.cpp', '.hpp'),'w+') as wf:
			wf.write(result[0])
			
		with open(outname,'w+') as wf:
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

def rReplace(string, toReplace, newValue, n = 1):
	return newValue.join(string.rsplit(toReplace,n))

def toSet(name): return f'set_{name}'
def toGet(name): return f'get_{name}'

def translate_type(type):
	if type == None: return 'void'
	if type == 'Variant': return type
	if type.endswith('[]'): return f'Array<{type[:-2]}>'
	if literal_type(type): return type
	return type + '*'

def type_enum(type):
	return 'Variant::' +  ( type.upper() if literal_type(type) else 'OBJECT' )

# ther are actually a lot of variant types (see @Globalscope.sml type enum)
def literal_type(type):
	return type in ['Array', 'Dictionary', 'string', 'int', 'float', 'bool', 'RID', 'Quaternion'] \
		or 'Vector' in type \
		or 'Transform' in type

# for prettier output
def prettify(value):
	def impl():
		cnt = 0
		for c in value:
			if c == '\n':
				cnt += 1
				if cnt < 3: yield c
			elif cnt > 0 and c == ';':  pass
			elif cnt > 0 and c == ' ':  yield c
			elif cnt > 0 and c == '\t': yield c
			else: cnt = 0; yield c
	return ''.join(impl())

# trick for generator values
get = next

hpp_template = '''
#ifndef __CLASS___H
#define __CLASS___H

#include <godot_cpp/godot.hpp>

using namespace godot;

namespace godot {

__IMPLEMENTATION__

}

#endif // __CLASS___H
'''

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

function_replacements = {
	'preload': "/* preload has no equivalent, add a 'ResourcePreloader' Node in your scene */",
	'weakref': 'Object::weak_ref(obj)',
	'instance_from_id' : 'Object::instance_from_id',
	'is_instance_id_valid' : 'Object::is_instance_id_valid',
	'is_instance_valid' : 'Object::is_instance_valid',
}