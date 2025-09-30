#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edit Everbyte .kat (BinaryFormatter) saves with missing assemblies.

Usage examples:
  # 1) Inspect as JSON
  python kat_edit.py dump /work/PersData.kat > save.json

  # 2) Edit fields and write a new file
  python kat_edit.py edit /work/PersData.kat /work/Patched.kat \
      --set coins=999999 \
      --set userSettings.energyCap=120 \
      --set paths[0].activeState=true \
      --set username="Alice"

Path syntax:
  - Dot for dict/field names:   userSettings.energyCap
  - Brackets for lists:         paths[0].memberIDs[2]
  - When a node is an Everbyte object, its fields live under Node.Data (handled automatically).
Value syntax:
  - Unquoted: numbers/bools/null (true/false/null) are typed; others become strings.
  - Quotes force string: "00123"
"""

import sys, os, json, re
import argparse

def _to_net(val):
    """Convert Python primitives to real .NET primitives for BinaryFormatter."""
    from System import Int32, Int64, Double, Boolean, String, Decimal
    if val is None:
        return None
    if isinstance(val, bool):
        return Boolean(val)
    if isinstance(val, int):
        # Int32 first, fall back to Int64, else Decimal
        if -2147483648 <= val <= 2147483647:
            return Int32(val)
        if -9223372036854775808 <= val <= 9223372036854775807:
            return Int64(val)
        return Decimal(val)  # very large ints
    if isinstance(val, float):
        return Double(val)
    if isinstance(val, str):
        return String(val)
    # Already a .NET object or unsupported python type: pass through
    return val

def build_helper_types():
    import clr
    try:
        clr.AddReference("System")
        clr.AddReference("System.Core")
        clr.AddReference("Microsoft.CSharp")
    except Exception:
        pass

    from Microsoft.CSharp import CSharpCodeProvider
    from System.CodeDom.Compiler import CompilerParameters

    cs = r'''
    using System;
    using System.Collections.Generic;
    using System.Runtime.Serialization;

    namespace KatRoundtrip {
      [Serializable]
      public class Node : ISerializable {
        public string FullTypeName;   // original .NET type name from the stream
        public string AssemblyName;   // original assembly name from the stream
        public Dictionary<string, object> Data = new Dictionary<string, object>();

        public Node() {}

        // Called by BinaryFormatter when we redirected to Node
        protected Node(SerializationInfo info, StreamingContext context) {
          this.FullTypeName = info.FullTypeName;
          this.AssemblyName = info.AssemblyName;
          foreach (SerializationEntry e in info) {
            Data[e.Name] = e.Value;
          }
        }

        // When serializing back, emit all captured fields and restore original headers
        public void GetObjectData(SerializationInfo info, StreamingContext context) {
          if (!string.IsNullOrEmpty(this.FullTypeName))
            info.FullTypeName = this.FullTypeName;
          if (!string.IsNullOrEmpty(this.AssemblyName))
            info.AssemblyName = this.AssemblyName;

          foreach (var kv in Data) {
            info.AddValue(kv.Key, kv.Value);
          }
        }
      }

      // Redirect Everbyte types -> Node on deserialize
      public class RedirectBinder : SerializationBinder {
        public override Type BindToType(string assemblyName, string typeName) {
          if (!string.IsNullOrEmpty(typeName) && typeName.StartsWith("Everbyte.TextGame.Saving"))
            return typeof(Node);
          if (!string.IsNullOrEmpty(assemblyName) && assemblyName.StartsWith("Everbyte.TextGame.Saving"))
            return typeof(Node);

          // Try default resolution for framework types (List`1, etc.)
          var full = string.IsNullOrEmpty(assemblyName) ? typeName : (typeName + ", " + assemblyName);
          var t = Type.GetType(full, throwOnError:false);
          if (t != null) return t;

          // If it's some other custom Everbyte type, still map to Node
          if (!string.IsNullOrEmpty(typeName) &&
              (typeName.IndexOf("Everbyte", StringComparison.OrdinalIgnoreCase) >= 0))
            return typeof(Node);

          // Last resort
          return typeof(object);
        }
      }
    }
    '''

    provider = CSharpCodeProvider()
    parms = CompilerParameters()
    parms.GenerateInMemory = True
    parms.GenerateExecutable = False
    parms.TreatWarningsAsErrors = False
    parms.ReferencedAssemblies.Add("System.dll")
    parms.ReferencedAssemblies.Add("System.Core.dll")
    parms.ReferencedAssemblies.Add("mscorlib.dll")

    res = provider.CompileAssemblyFromSource(parms, cs)
    if res.Errors.HasErrors:
        raise RuntimeError("\n".join(str(e) for e in res.Errors))

    asm = res.CompiledAssembly
    NodeType = asm.GetType("KatRoundtrip.Node")
    BinderType = asm.GetType("KatRoundtrip.RedirectBinder")
    return NodeType, BinderType

def deserialize(path, BinderType):
    from System.IO import FileStream, FileMode, FileAccess
    from System.Runtime.Serialization.Formatters.Binary import BinaryFormatter
    from System import Activator

    bf = BinaryFormatter()
    bf.Binder = Activator.CreateInstance(BinderType)

    fs = FileStream(path, FileMode.Open, FileAccess.Read)
    try:
        obj = bf.Deserialize(fs)
    finally:
        fs.Close()
    return obj

def serialize(path, obj):
    from System.IO import FileStream, FileMode, FileAccess
    from System.Runtime.Serialization.Formatters.Binary import BinaryFormatter

    bf = BinaryFormatter()
    fs = FileStream(path, FileMode.Create, FileAccess.Write)
    try:
        bf.Serialize(fs, obj)
    finally:
        fs.Close()

# ---------- JSON dump helpers (optional) ----------
def to_jsonable(o):
    from System import String, DateTime, Decimal, Guid, Array, Byte
    from System.Collections import IDictionary, IEnumerable
    from System.Reflection import BindingFlags
    from System.Runtime.CompilerServices import RuntimeHelpers

    seen = set()

    def conv(x):
        if x is None or isinstance(x, (str, int, float, bool)):
            return x
        try:
            oid = RuntimeHelpers.GetHashCode(x)
            if oid in seen:
                return None
            seen.add(oid)
        except Exception:
            pass

        tname = None
        try:
            tname = str(x.GetType().FullName)
        except Exception:
            tname = None

        if tname == "KatRoundtrip.Node":
            d = {"$original_dotnet_type": str(getattr(x, "FullTypeName", "")),
                 "$original_assembly":   str(getattr(x, "AssemblyName", ""))}
            data = getattr(x, "Data", None)
            if data is not None:
                py = {}
                for k in data.Keys:
                    py[str(k)] = conv(data[k])
                d.update(py)
            return d

        if tname is not None:
            # value-like
            if "System.DateTime" == tname:
                return x.ToString("o")
            if "System.Decimal" == tname:
                return float(x)
            if "System.Guid" == tname:
                return str(x)

        try:
            if isinstance(x, Array) and x.GetType().GetElementType() in (Byte,):
                return [int(b) for b in x]
        except Exception:
            pass

        # IDictionary
        from System.Collections import IDictionary as _IDict, IEnumerable as _IEnum
        if isinstance(x, _IDict):
            d = {}
            for k in x.Keys:
                d[str(k)] = conv(x[k])
            return d

        # IEnumerable (not string)
        if isinstance(x, _IEnum) and not isinstance(x, String):
            lst = []
            it = x.GetEnumerator()
            try:
                while it.MoveNext():
                    lst.append(conv(it.Current))
            except Exception:
                pass
            return lst

        # fallback reflection
        try:
            obj = {"$type": tname}
            flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
            for f in x.GetType().GetFields(flags):
                try:
                    obj[f.Name] = conv(f.GetValue(x))
                except Exception:
                    pass
            return obj
        except Exception:
            try:
                return str(x)
            except Exception:
                return None

    return conv(o)

# ---------- Path editing ----------
_path_token = re.compile(r"""
    (?: \. (?P<key>[A-Za-z_]\w*) )       # .field
  | (?: \[ (?P<idx>\d+) \] )             # [index]
  | (?: ^(?P<root>[A-Za-z_]\w*) )        # first token without dot
""", re.X)

def parse_path(s):
    tokens = []
    pos = 0
    while pos < len(s):
        m = _path_token.match(s, pos)
        if not m:
            raise ValueError(f"Invalid path near: {s[pos:]}")
        if m.group("root"): tokens.append(("key", m.group("root")))
        if m.group("key"):  tokens.append(("key", m.group("key")))
        if m.group("idx"):  tokens.append(("idx", int(m.group("idx"))))
        pos = m.end()
    return tokens

def get_node_data_if_any(obj):
    # If obj is our Node, return its Data dictionary; else None
    try:
        if str(obj.GetType().FullName) == "KatRoundtrip.Node":
            return getattr(obj, "Data")
    except Exception:
        pass
    return None

def traverse_for_set(root, path_tokens):
    """
    Walk path and return (parent, last_token) so we can assign.
    - On Nodes, we traverse into Node.Data.
    - On dict-like (.NET IDictionary), use keys.
    - On lists (IList/arrays), use indices.
    """
    from System.Collections import IDictionary
    from System import Array

    def dict_get(d, key):
        # Works for generic Dictionary<K,V> and non-generic IDictionary
        try:
            if hasattr(d, "ContainsKey") and d.ContainsKey(key):
                return d[key]
            if isinstance(d, IDictionary) and d.Contains(key):
                return d[key]
        except Exception:
            pass
        # last-resort: iterate Keys (slower)
        try:
            for k in d.Keys:
                if str(k) == str(key):
                    return d[k]
        except Exception:
            pass
        return None

    cur = root
    parent = None
    last = None

    for tk_kind, tk_val in path_tokens:
        parent = cur
        last = (tk_kind, tk_val)

        # auto-step into Node.Data when we’re on a KatRoundtrip.Node
        data = get_node_data_if_any(cur)
        if data is not None:
            cur = data

        if tk_kind == "key":
            if isinstance(cur, dict):
                cur = cur.get(tk_val, None)
            elif isinstance(cur, IDictionary) or hasattr(cur, "ContainsKey"):
                cur = dict_get(cur, tk_val)
            else:
                return parent, last, None

        elif tk_kind == "idx":
            try:
                cur = cur[tk_val]
            except Exception:
                # try IList-style get_Item
                try:
                    cur = cur.get_Item(tk_val)
                except Exception:
                    return parent, last, None

    return parent, last, cur

def parse_value_literal(s):
    # unquoted -> number/bool/null; quoted -> string (keep contents)
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    sl = s.lower()
    if sl == "true": return True
    if sl == "false": return False
    if sl == "null": return None
    # int or float
    try:
        if s.startswith("0") and len(s) > 1 and s[1].isdigit():
            # leading zeros -> treat as string unless quoted
            return s
        if "." in s or "e" in sl:
            return float(s)
        return int(s)
    except ValueError:
        return s

def set_value(root, path_expr, value_literal):
    tokens = parse_path(path_expr)
    parent, last, _cur = traverse_for_set(root, tokens)
    if parent is None or last is None:
        raise ValueError(f"Could not resolve path: {path_expr}")

    py_val = parse_value_literal(value_literal)
    net_val = _to_net(py_val)  # <<< important

    parent_data = get_node_data_if_any(parent)
    target = parent_data if parent_data is not None else parent

    kind, key = last
    from System.Collections import IDictionary
    if kind == "key":
        if hasattr(target, "ContainsKey") or isinstance(target, IDictionary):
            target[key] = net_val
        elif isinstance(target, dict):
            target[key] = py_val  # pure Python dict (unlikely)
        else:
            raise TypeError(f"Cannot assign key on {type(target)} at {path_expr}")
    elif kind == "idx":
        try:
            target[key] = net_val
        except Exception:
            try:
                target.set_Item(key, net_val)
            except Exception as e:
                raise TypeError(f"Cannot assign index {key}: {e}")

def cmd_dump(args):
    import clr
    NodeType, BinderType = build_helper_types()
    obj = deserialize(args.input, BinderType)
    j = to_jsonable(obj)
    json.dump(j, sys.stdout, ensure_ascii=False, indent=2)

def cmd_edit(args):
    import clr
    NodeType, BinderType = build_helper_types()
    obj = deserialize(args.input, BinderType)

    # apply all --set path=value
    for assignment in (args.set or []):
        if "=" not in assignment:
            raise ValueError(f"--set must be path=value, got: {assignment}")
        path, value = assignment.split("=", 1)
        set_value(obj, path.strip(), value.strip())

    serialize(args.output, obj)

def main():
    ap = argparse.ArgumentParser(description="Edit Everbyte .kat saves (BinaryFormatter) without original assemblies.")
    sp = ap.add_subparsers(dest="cmd", required=True)

    ap_dump = sp.add_parser("dump", help="Dump save to JSON")
    ap_dump.add_argument("input")
    ap_dump.set_defaults(func=cmd_dump)

    ap_edit = sp.add_parser("edit", help="Edit fields and write a new .kat")
    ap_edit.add_argument("input")
    ap_edit.add_argument("output")
    ap_edit.add_argument("--set", action="append", help='Path assignment like: coins=999 or userSettings.energyCap=120 or paths[0].activeState=true')
    ap_edit.set_defaults(func=cmd_edit)

    args = ap.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()

