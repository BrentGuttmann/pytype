"""Implementation of the types in Python 3's typing.py."""

# pylint's detection of this is error-prone:
# pylint: disable=unpacking-non-sequence


from pytype import abstract
from pytype.pytd import pep484
from pytype.pytd import pytd


class TypingOverlay(abstract.Module):
  """A representation of the 'typing' module that allows custom overlays."""

  is_lazy = True  # uses _convert_member

  def __init__(self, vm):
    member_map = typing_overload.copy()
    ast = vm.loader.typing
    for cls in ast.classes:
      _, name = cls.name.rsplit(".", 1)
      if name not in member_map and pytd.IsContainer(cls) and cls.template:
        member_map[name] = build_container
    super(TypingOverlay, self).__init__(vm, "typing", member_map)
    self.real_module = vm.convert.constant_to_value(
        ast, subst={}, node=vm.root_cfg_node)

  def _convert_member(self, name, m):
    var = m(name, self.vm).to_variable(self.vm.root_cfg_node)
    self.vm.trace_module_member(self, name, var)
    return var

  def get_module(self, name):
    if name in self._member_map:
      return self
    else:
      return self.real_module

  def items(self):
    items = super(TypingOverlay, self).items()
    for name, item in self.real_module.items():
      if name not in self._member_map:
        items.append((name, item))
    return items


class Union(abstract.AnnotationClass):
  """Implementation of typing.Union[...]."""

  def __init__(self, name, vm, options=()):
    super(Union, self).__init__(name, vm)
    self.options = options

  def _build_value(self, node, inner):
    return abstract.Union(self.options + inner, self.vm)


class Callable(abstract.AnnotationContainer):

  def __init__(self, name, vm):
    base = abstract.get_atomic_value(vm.convert.function_type)
    super(Callable, self).__init__(name, vm, base)

  def _build_value(self, node, inner):
    # We don't do anything with Callable parameters yet.
    return self.base_cls


class TypeVarError(Exception):
  """Raised if an error is encountered while initializing a TypeVar."""

  def __init__(self, message, bad_call=None):
    super(TypeVarError, self).__init__(message)
    self.bad_call = bad_call


class TypeVar(abstract.PyTDFunction):
  """Representation of typing.TypeVar, as a function."""

  def __init__(self, name, vm):
    pyval = vm.loader.typing.Lookup("typing._typevar_new")
    f = vm.convert.constant_to_value(pyval, {}, vm.root_cfg_node)
    super(TypeVar, self).__init__(name, f.signatures, pytd.METHOD, vm)
    vm.errorlog.not_supported_yet(vm.frame.current_opcode, name)

  def _get_class_or_constant(self, var, name, arg_type):
    if arg_type is abstract.Class:
      convert_func = abstract.get_atomic_value
      type_desc = "an unambiguous type"
    else:
      convert_func = abstract.get_atomic_python_constant
      type_desc = "a constant " + arg_type.__name__
    try:
      return convert_func(var, arg_type)
    except abstract.ConversionError:
      raise TypeVarError("%s must be %s" % (name, type_desc))

  def _get_namedarg(self, args, name, arg_type, default_value):
    if name in args.namedargs:
      value = self._get_class_or_constant(args.namedargs[name], name, arg_type)
      self.vm.errorlog.not_supported_yet(
          self.vm.frame.current_opcode, "argument \"%s\" to TypeVar" % name)
      return value
    return default_value

  def _get_typeparam(self, node, args):
    args = args.simplify(node)
    try:
      self._match_args(node, args)
    except abstract.InvalidParameters as e:
      raise TypeVarError("wrong arguments", e.bad_call)
    except abstract.FailedFunctionCall:
      # It is currently impossible to get here, since the only
      # FailedFunctionCall that is not an InvalidParameters is NotCallable.
      raise TypeVarError("initialization failed")
    name = self._get_class_or_constant(args.posargs[0], "name", str)
    constraints = tuple(self._get_class_or_constant(
        c, "constraint", abstract.Class) for c in args.posargs[1:])
    if len(constraints) == 1:
      raise TypeVarError("the number of constraints must be 0 or more than 1")
    bound = self._get_namedarg(args, "bound", abstract.Class, None)
    covariant = self._get_namedarg(args, "covariant", bool, False)
    contravariant = self._get_namedarg(args, "contravariant", bool, False)
    if constraints and bound:
      raise TypeVarError("constraints and a bound are mutually exclusive")
    extra_kwargs = set(args.namedargs) - {"bound", "covariant", "contravariant"}
    if extra_kwargs:
      raise TypeVarError("extra keyword arguments: " + ", ".join(extra_kwargs))
    if args.starargs:
      raise TypeVarError("*args must be a constant tuple")
    if args.starstarargs:
      raise TypeVarError("ambiguous **kwargs not allowed")
    return abstract.TypeParameter(name, self.vm, constraints=constraints,
                                  bound=bound, covariant=covariant,
                                  contravariant=contravariant)

  def call(self, node, _, args):
    """Call typing.TypeVar()."""
    try:
      param = self._get_typeparam(node, args)
    except TypeVarError as e:
      self.vm.errorlog.invalid_typevar(
          self.vm.frame.current_opcode, e.message, e.bad_call)
      return node, self.vm.convert.unsolvable.to_variable(node)
    return node, param.to_variable(node)


def build_container(name, vm):
  if name in pep484.PEP484_CAPITALIZED:
    pytd_name = "__builtin__." + name.lower()
  else:
    pytd_name = "typing." + name
  base = vm.convert.name_to_value(pytd_name)
  return abstract.AnnotationContainer(name, vm, base)


def build_any(name, vm):
  del name
  return abstract.Unsolvable(vm)


# TODO(kramm): Do a full implementation of this.
def build_namedtuple(name, vm):
  del name
  return abstract.Unsolvable(vm)


def build_optional(name, vm):
  return Union(name, vm, (vm.convert.none_type.data[0],))


def build_generic(name, vm):
  vm.errorlog.not_supported_yet(vm.frame.current_opcode, name)
  return vm.convert.unsolvable


def build_typechecking(name, vm):
  del name
  return vm.convert.true


typing_overload = {
    "Any": build_any,
    "Callable": Callable,
    "Generic": build_generic,
    "NamedTuple": build_namedtuple,
    "Optional": build_optional,
    "TypeVar": TypeVar,
    "Union": Union,
    "TYPE_CHECKING": build_typechecking,
}
