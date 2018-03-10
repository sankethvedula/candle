class Package(object):
    """
    Convenience data structure for performing operations on nested list groups. For example,
    a = Package(["a", "b", ["d", "e"]])
    (a + " ").reify() ==> ["a ", "b ", ["d ", "e "]]
    """

    def __init__(self, children, children_type=None):
        assert len(children) != 0 or children_type
        self.children = self._build_children(children)
        self.children_type = children_type if children_type else self._discover_type()

    def _build_children(self, children):
        children_list = []
        for child in children:
            children_list.append(Package(child) if isinstance(child, list) else child)
        return children_list

    def _discover_type(self):
        for child in self.children:
            if isinstance(child, Package):
                return child._discover_type()
            return type(child)

    @property
    def singleton(self):
        return self.children[0]

    def reify(self, flat=False):
        reified = [item.reify() if isinstance(item, Package) else item for item in self.children]
        if flat:
            reified = flatten(reified)
        return reified

    def _apply_fn(self, function, elements, *args):
        data = []
        for params in zip(elements, *args):
            e, p_args = params[0], params[1:]
            if isinstance(e, Package):
                data.append(self._apply_fn(function, e.children, *[arg.children for arg in p_args]))
            else:
                data.append(function(e, *p_args))
        return Package(data)

    def apply_fn(self, function, *args):
        return self._apply_fn(function, self.children, *[arg.children for arg in args])

    def __getattribute__(self, name):
        def wrap_attr(attr_name, elements):
            def get_attr(*args, **kwargs):
                use_pkg_iter = False
                for arg in args:
                    if isinstance(arg, Package):
                        args = arg.children
                        use_pkg_iter = True
                        break

                new_elems = []
                for i, element in enumerate(elements):
                    new_args = (args[i],) if use_pkg_iter else args
                    if isinstance(element, Package):
                        new_elem = wrap_attr(attr_name, element.children)(*new_args, **kwargs)
                    else:
                        attr = getattr(element, attr_name)
                        new_elem = attr(*new_args, **kwargs) if callable(attr) else attr
                    new_elems.append(new_elem)
                return Package(new_elems)
            return get_attr if callable(getattr(self.children_type, name)) else get_attr()

        if name in ("children", "children_type", "__getattribute__", "_discover_type", 
                "_build_children", "reify", "apply_fn", "_apply_fn", "singleton"):
            return object.__getattribute__(self, name)
        return wrap_attr(name, self.children)

    def __add__(self, other): return self.__getattribute__("__add__")(other)
    def __sub__(self, other): return self.__getattribute__("__sub__")(other)
    def __mul__(self, other): return self.__getattribute__("__mul__")(other)
    def __truediv__(self, other): return self.__getattribute__("__truediv__")(other)
    def __floordiv__(self, other): return self.__getattribute__("__floordiv__")(other)
    def __div__(self, other): return self.__getattribute__("__div__")(other)
    def __mod__(self, other): return self.__getattribute__("__mod__")(other)
    def __divmod__(self, other): return self.__getattribute__("__divmod__")(other)
    def __pow__(self, other): return self.__getattribute__("__pow__")(other)
    def __lshift__(self, other): return self.__getattribute__("__lshift__")(other)
    def __rshift__(self, other): return self.__getattribute__("__rshift__")(other)
    def __and__(self, other): return self.__getattribute__("__and__")(other)
    def __xor__(self, other): return self.__getattribute__("__xor__")(other)
    def __or__(self, other): return self.__getattribute__("__or__")(other)
    def __radd__(self, other): return self.__getattribute__("__radd__")(other)
    def __rsub__(self, other): return self.__getattribute__("__rsub__")(other)
    def __rmul__(self, other): return self.__getattribute__("__rmul__")(other)
    def __rdiv__(self, other): return self.__getattribute__("__rdiv__")(other)
    def __rmod__(self, other): return self.__getattribute__("__rmod__")(other)
    def __rdivmod__(self, other): return self.__getattribute__("__rdivmod__")(other)
    def __rpow__(self, other): return self.__getattribute__("__rpow__")(other)
    def __rlshift__(self, other): return self.__getattribute__("__rlshift__")(other)
    def __rrshift__(self, other): return self.__getattribute__("__rrshift__")(other)
    def __rand__(self, other): return self.__getattribute__("__rand__")(other)
    def __rxor__(self, other): return self.__getattribute__("__rxor__")(other)
    def __ror__(self, other): return self.__getattribute__("__ror__")(other)
    def __neg__(self): return self.__getattribute__("__neg__")()
    def __pos__(self): return self.__getattribute__("__pos__")()
    def __abs__(self): return self.__getattribute__("__abs__")()
    def __invert__(self): return self.__getattribute__("__invert__")()
    def __complex__(self): return self.__getattribute__("__complex__")()
    def __int__(self): return self.__getattribute__("__int__")()
    def __long__(self): return self.__getattribute__("__long__")()
    def __float__(self): return self.__getattribute__("__float__")()
    def __getitem__(self, key): return self.__getattribute__("__getitem__")(key)
    def __setitem__(self, key, value): return self.__getattribute__("__setitem__")(key, value)

def flatten_zip(*args):
    args = [flatten(arg) for arg in args]
    return zip(*args)

def nested_map(fn, nested_list):
    return [nested_map(fn, e) if isinstance(e, list) else fn(e) for e in nested_list]

def nested_builder(target, *args):
    for elements in zip(args):
        if isinstance(elements[0], list):
            cb_element_list = []
            yield nested_builder(cb_element_list, *elements)
            target.append(cb_element_list)
        else:
            yield target, elements

def flatten(nested_list):
    items = []
    for elem in nested_list:
        if isinstance(elem, list):
            items.extend(flatten(elem))
        else:
            items.append(elem)
    return items
