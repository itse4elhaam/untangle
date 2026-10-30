"""Read-only X11 geometry/input inspection of our windows and their WM frames."""


def native_window_state(window_id):
    from Xlib import display
    from Xlib.ext import shape
    connection = display.Display()
    try:
        root = connection.screen().root
        pointer_child = root.query_pointer().child
        result = dict(pointer_child=getattr(pointer_child, 'id', pointer_child), windows=[])
        window = connection.create_resource_object('window', window_id)
        # Include WM reparenting frames, which can differ from QWidget geometry.
        for _ in range(3):
            if window.id == root.id:
                break
            geometry, attributes = window.get_geometry(), window.get_attributes()
            parent = window.query_tree().parent
            rectangles = window.shape_get_rectangles(shape.SK.Input).rectangles
            bounds = None
            if rectangles:
                left, top = min(r.x for r in rectangles), min(r.y for r in rectangles)
                right = max(r.x + r.width for r in rectangles)
                bottom = max(r.y + r.height for r in rectangles)
                bounds = [left, top, right - left, bottom - top]
            result['windows'].append(dict(window_id=window.id, parent_id=parent.id,
                geometry=[geometry.x, geometry.y, geometry.width, geometry.height],
                mapped=attributes.map_state, override_redirect=bool(attributes.override_redirect),
                input_rectangles=len(rectangles), input_bounds=bounds))
            window = parent
        return result
    finally:
        connection.close()
