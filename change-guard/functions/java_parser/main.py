import functions_framework
import json
import javalang
import hashlib

# --- Main Handler ---
@functions_framework.http
def handler(request):
    """
    Parses Java code to identify atomic changes, including
    Change Method Body (CM) and Delete Class (DC).
    """
    request_json = request.get_json(silent=True)
    if not request_json:
        return "ERROR: Invalid JSON.", 400

    filename = request_json.get("filename")
    before_content = request_json.get("before_content", "")
    after_content = request_json.get("after_content", "")

    if not filename:
        return "ERROR: Missing 'filename' in request.", 400

    print(f"Parsing file: {filename}")
    atomic_changes = []

    try:
        tree_before = javalang.parse.parse(before_content) if before_content else None
        tree_after = javalang.parse.parse(after_content) if after_content else None

        # Case 1: File was modified
        if tree_before and tree_after:
            changes = diff_trees(tree_before, tree_after, filename)
            atomic_changes.extend(changes)
        # Case 2: File was newly created
        elif tree_after:
            class_declarations = get_class_declarations(tree_after)
            if class_declarations:
                class_declaration = class_declarations[0]
                methods_after = get_methods_from_ast(tree_after)
                for method_name, node in methods_after.items():
                     atomic_changes.append({
                        "type": "AM", "details": f"Method '{method_name}' added in new file.",
                        "file": filename, "class": class_declaration.name,
                        "method": method_name, "line": node.position.line if node.position else 'N/A'
                    })
        # Case 3: File was deleted
        elif tree_before:
            class_declarations = get_class_declarations(tree_before)
            if class_declarations:
                class_declaration = class_declarations[0]
                atomic_changes.append({
                    "type": "DC", "details": f"Class '{class_declaration.name}' and its file were deleted.",
                    "file": filename, "class": class_declaration.name
                })

        print(f"Found changes: {atomic_changes}")
        return json.dumps(atomic_changes), 200, {'Content-Type': 'application/json'}

    except javalang.tokenizer.LexerError as e:
        print(f"ERROR: Could not parse Java code in {filename}. Error: {e}")
        return json.dumps([]), 200, {'Content-Type': 'application/json'}
    except Exception as e:
        print(f"An unexpected error occurred during parsing: {e}")
        raise e

def get_class_declarations(tree):
    return [cls for cls in tree.types if isinstance(cls, javalang.tree.ClassDeclaration)]

def get_methods_from_ast(tree):
    methods = {}
    class_declarations = get_class_declarations(tree)
    if not class_declarations: return methods
    
    class_declaration = class_declarations[0]
    for _, method_node in class_declaration.filter(javalang.tree.MethodDeclaration):
        methods[method_node.name] = method_node
    return methods

def get_method_body_hash(method_node):
    """
    Tokenizes a method's body and returns a hash of the token sequence.
    """
    if not method_node.body:
        return None 

    tokens = []
    for statement in method_node.body:
        if hasattr(statement, 'filter'):
             # --- THIS IS THE FIX ---
             # The correct class to filter for is javalang.tokenizer.JavaTokenizer
             for token in statement.filter(javalang.tokenizer.JavaTokenizer):
                tokens.append(token.value)

    body_string = "".join(tokens)
    return hashlib.sha256(body_string.encode('utf-8')).hexdigest()

def diff_trees(tree_before, tree_after, filename):
    changes = []
    class_declarations_after = get_class_declarations(tree_after)
    if not class_declarations_after: return []

    class_name = class_declarations_after[0].name
    methods_before = get_methods_from_ast(tree_before)
    methods_after = get_methods_from_ast(tree_after)

    added_method_names = set(methods_after.keys()) - set(methods_before.keys())
    for name in added_method_names:
        changes.append({
            "type": "AM", "details": f"Method '{name}' was added.",
            "file": filename, "class": class_name, "method": name,
            "line": methods_after[name].position.line if methods_after[name].position else 'N/A'
        })

    deleted_method_names = set(methods_before.keys()) - set(methods_after.keys())
    for name in deleted_method_names:
        changes.append({
            "type": "DM", "details": f"Method '{name}' was deleted.",
            "file": filename, "class": class_name, "method": name
        })

    common_method_names = set(methods_before.keys()) & set(methods_after.keys())
    for name in common_method_names:
        method_before = methods_before[name]
        method_after = methods_after[name]

        hash_before = get_method_body_hash(method_before)
        hash_after = get_method_body_hash(method_after)

        if hash_before and hash_after and hash_before != hash_after:
            changes.append({
                "type": "CM", "details": f"The body of method '{name}' was changed.",
                "file": filename, "class": class_name, "method": name,
                "line": method_after.position.line if method_after.position else 'N/A'
            })
    return changes
