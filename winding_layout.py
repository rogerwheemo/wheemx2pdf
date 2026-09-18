"""
Winding Layout Generator for BLDC/PMSM Motors

Generates winding schemas and visualizations for 3-phase motors based on
slot count and pole count. Inspired by Bewicklungsrechner XL.

Original algorithm: (C) 2010 Felix Niessen (Bewicklungsrechner XL)
Python implementation for WheemX PDF datasheets.
"""

import math
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Circle, Line, String, Polygon, Rect


# Phase colors (matching standard convention)
PHASE_COLORS = {
    'A': colors.HexColor('#EA0000'),  # Red
    'a': colors.HexColor('#EA0000'),
    'B': colors.HexColor('#008AE6'),  # Blue
    'b': colors.HexColor('#008AE6'),
    'C': colors.HexColor('#00CA00'),  # Green
    'c': colors.HexColor('#00CA00'),
    '-': colors.HexColor('#888888'),  # Empty/neutral
    '|': colors.HexColor('#000000'),  # Separator
}


def generate_winding_schema(num_slots: int, num_poles: int, single_layer: bool = False) -> dict:
    """
    Generate the winding schema for a 3-phase motor.
    
    Args:
        num_slots: Number of stator slots (must be divisible by 3)
        num_poles: Number of magnetic poles (must be even)
        single_layer: If True, generate single-layer winding (default: double-layer)
    
    Returns:
        Dictionary with:
        - schema: The winding pattern string (e.g., "AaCcBbAaCcBb")
        - distributed: Whether this is a distributed winding
        - balanced: Whether the winding is balanced
        - slot_assignments: List of phase assignments per slot
        - cogging_steps: Number of cogging steps per revolution (LCM)
    """
    # Validation
    if num_slots % 3 != 0 or num_slots < 3:
        raise ValueError("Number of slots must be divisible by 3 and >= 3")
    if num_poles % 2 != 0 or num_poles < 2:
        raise ValueError("Number of poles must be even and >= 2")
    if num_poles == num_slots:
        raise ValueError("Number of poles must be different from number of slots")
    
    # Calculate slots per pole per phase (Lochzahl)
    slots_per_pole_per_phase = num_slots / 3 / num_poles
    distributed = slots_per_pole_per_phase >= 1
    
    # Electrical angle per slot
    angle_per_slot = 180 * num_poles / num_slots
    
    # Count phases
    counts = {'a': 0, 'b': 0, 'c': 0, 'A': 0, 'B': 0, 'C': 0}
    schema = ""
    current_angle = 0
    
    if not distributed:
        # Concentrated winding
        for i in range(num_slots):
            if i % 2 != 0 and single_layer:
                schema += "-"
            else:
                phase = _get_phase_for_angle(current_angle)
                schema += phase
                counts[phase] += 1
            current_angle = (current_angle + angle_per_slot) % 360
    else:
        # Distributed winding - each slot gets a phase assignment
        for i in range(num_slots):
            phase = _get_phase_for_angle(current_angle)
            schema += phase + "|"
            counts[phase] += 1
            current_angle = (current_angle + angle_per_slot) % 360
    
    # Normalize schema to start with 'A' if possible
    schema = _normalize_schema(schema, counts)
    
    # Check if balanced
    balanced = (counts['a'] == counts['b'] == counts['c'] and 
                counts['A'] == counts['B'] == counts['C'])
    
    # Calculate LCM for cogging steps
    cogging_steps = _lcm(num_slots, num_poles)
    
    # Calculate ripple steps (torque ripple frequency)
    # For 3-phase motors: ripple = LCM(slots, 6*pole_pairs) per revolution
    # This accounts for 6-step commutation harmonics interacting with slot harmonics
    pole_pairs = num_poles // 2
    ripple_steps = _lcm(num_slots, 6 * pole_pairs)
    
    # Parse slot assignments for visualization
    if distributed:
        slot_assignments = _parse_distributed_schema(schema)
    else:
        slot_assignments = _parse_concentrated_schema(schema, single_layer)
    
    return {
        'schema': schema.rstrip('|'),
        'schema_display': _format_schema_display(schema),
        'distributed': distributed,
        'balanced': balanced,
        'slot_assignments': slot_assignments,
        'cogging_steps': cogging_steps,
        'ripple_steps': ripple_steps,
        'num_slots': num_slots,
        'num_poles': num_poles,
    }


def _get_phase_for_angle(angle: float) -> str:
    """Get the phase assignment based on electrical angle."""
    angle = angle % 360
    if angle >= 330 or angle < 30:
        return 'A'
    elif 30 <= angle < 90:
        return 'b'
    elif 90 <= angle < 150:
        return 'C'
    elif 150 <= angle < 210:
        return 'a'
    elif 210 <= angle < 270:
        return 'B'
    else:  # 270 <= angle < 330
        return 'c'


def _normalize_schema(schema: str, counts: dict) -> str:
    """Normalize schema to start with uppercase A and maintain phase order."""
    # Rotate to not end with 'a' or 'A'
    if counts['a'] > 0 and counts['A'] > 0:
        while schema[-1] in ('a', 'A', '|'):
            if schema[-1] == '|':
                schema = schema[-2:] + schema[:-2]
            else:
                schema = schema[-1] + schema[:-1]
    
    # If starts with lowercase 'a', swap all cases
    if schema and schema[0] == 'a':
        schema = _swap_cases(schema)
    
    # Ensure B comes before C in sequence
    b_pos = -1
    c_pos = -1
    for i, ch in enumerate(schema):
        if ch.lower() == 'b' and b_pos < 0:
            b_pos = i
        if ch.lower() == 'c' and c_pos < 0:
            c_pos = i
    
    if b_pos >= 0 and c_pos >= 0 and b_pos > c_pos:
        schema = _swap_bc(schema)
    
    return schema


def _swap_cases(schema: str) -> str:
    """Swap uppercase and lowercase for all phases."""
    result = ""
    for ch in schema:
        if ch == 'a':
            result += 'A'
        elif ch == 'A':
            result += 'a'
        elif ch == 'b':
            result += 'B'
        elif ch == 'B':
            result += 'b'
        elif ch == 'c':
            result += 'C'
        elif ch == 'C':
            result += 'c'
        else:
            result += ch
    return result


def _swap_bc(schema: str) -> str:
    """Swap B and C phases."""
    result = ""
    for ch in schema:
        if ch == 'b':
            result += 'c'
        elif ch == 'c':
            result += 'b'
        elif ch == 'B':
            result += 'C'
        elif ch == 'C':
            result += 'B'
        else:
            result += ch
    return result


def _lcm(a: int, b: int) -> int:
    """Calculate Least Common Multiple."""
    return abs(a * b) // math.gcd(a, b)


def _parse_distributed_schema(schema: str) -> list:
    """Parse distributed winding schema into slot assignments."""
    parts = schema.split('|')
    assignments = []
    for part in parts:
        if part:
            # For distributed, we create double-layer by repeating
            assignments.append([part, part.swapcase()])
    return assignments


def _parse_concentrated_schema(schema: str, single_layer: bool) -> list:
    """Parse concentrated winding schema into slot assignments."""
    assignments = []
    for i, ch in enumerate(schema):
        if ch == '-':
            assignments.append(['-'])
        elif single_layer:
            assignments.append([ch])
        else:
            # Double layer: each slot has the phase and its opposite in adjacent
            if i > 0 and schema[i-1] != '-':
                prev = schema[i-1]
                assignments.append([prev.swapcase(), ch])
            else:
                assignments.append([ch, ch])
    return assignments


def _format_schema_display(schema: str) -> str:
    """Format schema for display (remove separators, clean up)."""
    return schema.replace('|', '')


def create_circular_stator_drawing(winding_info: dict, size: int = 50) -> Drawing:
    """
    Create a circular stator visualization showing windings with endwindings.
    
    Args:
        winding_info: Dictionary from generate_winding_schema()
        size: Drawing size in points
    
    Returns:
        ReportLab Drawing object
    """
    drawing = Drawing(size, size)
    cx, cy = size / 2, size / 2
    
    num_slots = winding_info['num_slots']
    num_poles = winding_info['num_poles']
    schema = winding_info['schema_display']
    
    # Radii - adjusted for better proportions
    outer_radius = size * 0.42
    inner_radius = size * 0.22
    tooth_height = outer_radius - inner_radius - 8
    tooth_base_radius = inner_radius + 4
    endwinding_radius = inner_radius - 8  # Inside the air gap for endwindings
    
    # Draw outer ring (rotor area indication)
    drawing.add(Circle(cx, cy, outer_radius + 20,
                       fillColor=colors.HexColor('#EEEEEE'),
                       strokeColor=colors.HexColor('#AAAAAA'),
                       strokeWidth=1))
    
    # Draw poles on rotor
    pole_radius = outer_radius + 12
    angle_per_pole = 360 / num_poles
    for i in range(num_poles):
        angle_start = math.radians(i * angle_per_pole - angle_per_pole * 0.4)
        angle_end = math.radians(i * angle_per_pole + angle_per_pole * 0.4)
        pole_color = colors.HexColor('#FFAAAA') if i % 2 == 0 else colors.HexColor('#AAAAFF')
        _draw_arc(drawing, cx, cy, pole_radius, angle_start, angle_end, pole_color, 8)
    
    # Draw stator back iron circle
    drawing.add(Circle(cx, cy, outer_radius,
                       fillColor=None,
                       strokeColor=colors.HexColor('#333333'),
                       strokeWidth=2))
    
    # Draw inner circle (air gap boundary)
    drawing.add(Circle(cx, cy, inner_radius,
                       fillColor=colors.white,
                       strokeColor=colors.HexColor('#333333'),
                       strokeWidth=1))
    
    # Calculate slot angles
    angle_per_slot = 360 / num_slots
    tooth_width_angle = angle_per_slot * 0.35
    
    # First pass: Draw all teeth (black background)
    for i in range(num_slots):
        angle = math.radians(i * angle_per_slot - 90)  # Start from top
        _draw_tooth(drawing, cx, cy, tooth_base_radius, tooth_height,
                    angle, math.radians(tooth_width_angle))
    
    # Second pass: Draw endwindings (arcs connecting coils)
    _draw_endwindings(drawing, cx, cy, endwinding_radius, schema, num_slots, num_poles)
    
    # Third pass: Draw windings on teeth with direction
    for i in range(num_slots):
        angle = math.radians(i * angle_per_slot - 90)
        if i < len(schema):
            phase = schema[i]
            if phase != '-':
                color = PHASE_COLORS.get(phase, colors.gray)
                _draw_winding_on_tooth(drawing, cx, cy, tooth_base_radius, tooth_height,
                                       angle, math.radians(tooth_width_angle), color,
                                       is_positive=phase.isupper())
    
    # Fourth pass: Draw slot numbers (larger, on outer edge)
    for i in range(num_slots):
        angle = math.radians(i * angle_per_slot - 90)
        num_radius = outer_radius + 6
        num_x = cx + num_radius * math.cos(angle)
        num_y = cy + num_radius * math.sin(angle)
        
        # Rotate text to be readable (pointing outward)
        rotation = math.degrees(angle) + 90
        if 90 < rotation < 270:
            rotation += 180
        
        drawing.add(String(num_x, num_y - 4, str(i + 1),
                           fontSize=9, fontName='Helvetica-Bold',
                           fillColor=colors.HexColor('#333333'),
                           textAnchor='middle'))
    
    return drawing


def _draw_endwindings(drawing: Drawing, cx: float, cy: float, radius: float,
                      schema: str, num_slots: int, num_poles: int):
    """Draw endwinding arcs connecting coils of the same phase."""
    angle_per_slot = 360 / num_slots
    coil_pitch = num_slots // num_poles  # Slots spanned by one coil
    
    # Track which connections we've drawn to avoid duplicates
    drawn_connections = set()
    
    for i, phase in enumerate(schema):
        if phase == '-':
            continue
        
        color = PHASE_COLORS.get(phase, colors.gray)
        
        # Find the next slot of the same phase (considering coil pitch)
        # For concentrated windings, connect adjacent same-phase slots
        for j in range(i + 1, min(i + coil_pitch + 2, len(schema))):
            j_mod = j % len(schema)
            if schema[j_mod].lower() == phase.lower():
                # Create connection key to avoid duplicates
                conn_key = (min(i, j_mod), max(i, j_mod), phase.lower())
                if conn_key in drawn_connections:
                    continue
                drawn_connections.add(conn_key)
                
                # Draw arc from slot i to slot j on inner side
                angle1 = math.radians(i * angle_per_slot - 90)
                angle2 = math.radians(j_mod * angle_per_slot - 90)
                
                # Determine arc radius based on distance
                slot_diff = abs(j_mod - i)
                arc_radius = radius - slot_diff * 3  # Vary radius to avoid overlap
                arc_radius = max(arc_radius, radius * 0.4)  # Minimum radius
                
                _draw_endwinding_arc(drawing, cx, cy, arc_radius, angle1, angle2, color)
                break  # Only connect to nearest same-phase slot


def _draw_endwinding_arc(drawing: Drawing, cx: float, cy: float, radius: float,
                         angle1: float, angle2: float, color):
    """Draw an endwinding arc connecting two slots on the inner side."""
    # Draw a smooth arc from angle1 to angle2
    steps = 15
    angle_diff = angle2 - angle1
    # Normalize to take shorter path
    if angle_diff > math.pi:
        angle_diff -= 2 * math.pi
    elif angle_diff < -math.pi:
        angle_diff += 2 * math.pi
    
    angle_step = angle_diff / steps
    for i in range(steps):
        a1 = angle1 + i * angle_step
        a2 = angle1 + (i + 1) * angle_step
        x1 = cx + radius * math.cos(a1)
        y1 = cy + radius * math.sin(a1)
        x2 = cx + radius * math.cos(a2)
        y2 = cy + radius * math.sin(a2)
        drawing.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=2))


def _draw_arc(drawing: Drawing, cx: float, cy: float, radius: float,
              start_angle: float, end_angle: float, color, width: float):
    """Draw an arc using line segments."""
    steps = 20
    angle_step = (end_angle - start_angle) / steps
    for i in range(steps):
        a1 = start_angle + i * angle_step
        a2 = start_angle + (i + 1) * angle_step
        x1 = cx + radius * math.cos(a1)
        y1 = cy + radius * math.sin(a1)
        x2 = cx + radius * math.cos(a2)
        y2 = cy + radius * math.sin(a2)
        drawing.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=width))


def _draw_tooth(drawing: Drawing, cx: float, cy: float, base_radius: float,
                height: float, angle: float, width_angle: float):
    """Draw a stator tooth."""
    # Tooth base corners
    r1 = base_radius
    r2 = base_radius + height
    
    # Calculate corner points
    a1 = angle - width_angle / 2
    a2 = angle + width_angle / 2
    
    points = [
        cx + r1 * math.cos(a1), cy + r1 * math.sin(a1),
        cx + r2 * math.cos(a1), cy + r2 * math.sin(a1),
        cx + r2 * math.cos(a2), cy + r2 * math.sin(a2),
        cx + r1 * math.cos(a2), cy + r1 * math.sin(a2),
    ]
    
    drawing.add(Polygon(points, fillColor=colors.HexColor('#444444'),
                       strokeColor=colors.HexColor('#222222'), strokeWidth=1))


def _draw_winding_on_tooth(drawing: Drawing, cx: float, cy: float, base_radius: float,
                           height: float, angle: float, width_angle: float,
                           color, is_positive: bool):
    """Draw winding coils around a tooth with direction-dependent diagonal lines."""
    # Draw multiple turns representation with direction
    num_turns = 5
    turn_spacing = height / (num_turns + 1.5)
    
    a_left = angle - width_angle * 0.8
    a_right = angle + width_angle * 0.8
    
    for t in range(num_turns):
        r_base = base_radius + turn_spacing * (t + 0.8)
        r_top = r_base + turn_spacing * 0.7
        
        if is_positive:
            # Positive: diagonal lines go from bottom-left to top-right
            x1 = cx + r_base * math.cos(a_left)
            y1 = cy + r_base * math.sin(a_left)
            x2 = cx + r_top * math.cos(a_right)
            y2 = cy + r_top * math.sin(a_right)
        else:
            # Negative: diagonal lines go from bottom-right to top-left
            x1 = cx + r_base * math.cos(a_right)
            y1 = cy + r_base * math.sin(a_right)
            x2 = cx + r_top * math.cos(a_left)
            y2 = cy + r_top * math.sin(a_left)
        
        drawing.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=2))
    
    # Draw direction indicator (+ or -) at the middle of the tooth
    indicator_r = base_radius + height * 0.5
    ind_x = cx + indicator_r * math.cos(angle)
    ind_y = cy + indicator_r * math.sin(angle)
    
    # Draw a small circle with + or - inside
    drawing.add(Circle(ind_x, ind_y, 6, fillColor=colors.white,
                       strokeColor=color, strokeWidth=1.5))
    symbol = "+" if is_positive else "-"
    drawing.add(String(ind_x, ind_y - 3, symbol, fontSize=9, fontName='Helvetica-Bold',
                       fillColor=color, textAnchor='middle'))


def create_linear_slot_diagram(winding_info: dict, width: int = 500, slot_height: int = 30) -> Drawing:
    """
    Create a linear slot diagram showing the winding pattern.
    
    Args:
        winding_info: Dictionary from generate_winding_schema()
        width: Drawing width in points
        slot_height: Height per slot row
    
    Returns:
        ReportLab Drawing object
    """
    num_slots = winding_info['num_slots']
    schema = winding_info['schema_display']
    num_poles = winding_info['num_poles']
    
    # Calculate dimensions
    height = slot_height * min(num_slots, 24) + 60  # Cap display for many slots
    slots_to_show = min(num_slots, 24)
    
    drawing = Drawing(width, height)
    
    # Layout
    left_margin = 50
    slot_width = 40
    coil_span = (width - left_margin - 100) / 2
    center_x = width / 2
    
    # Header
    drawing.add(String(center_x, height - 15, "Winding Diagram", 
                      fontSize=10, fontName='Helvetica-Bold',
                      fillColor=colors.HexColor('#333333'), textAnchor='middle'))
    
    # Draw slots and connections
    y_start = height - 40
    
    for i in range(slots_to_show):
        y = y_start - i * slot_height
        
        # Slot box
        drawing.add(Rect(center_x - slot_width/2, y - slot_height/2 + 5,
                        slot_width, slot_height - 10,
                        fillColor=colors.HexColor('#333333'),
                        strokeColor=colors.HexColor('#222222'),
                        strokeWidth=1))
        
        # Slot number
        drawing.add(String(center_x, y - 3, str(i + 1),
                          fontSize=9, fontName='Helvetica-Bold',
                          fillColor=colors.white, textAnchor='middle'))
        
        # Phase assignment
        if i < len(schema):
            phase = schema[i]
            if phase != '-':
                color = PHASE_COLORS.get(phase, colors.gray)
                
                # Left side coil end (entry)
                entry_x = center_x - slot_width/2 - 5
                drawing.add(Line(entry_x, y, center_x - slot_width/2, y,
                               strokeColor=color, strokeWidth=2))
                
                # Right side coil end (exit)
                exit_x = center_x + slot_width/2 + 5
                drawing.add(Line(center_x + slot_width/2, y, exit_x, y,
                               strokeColor=color, strokeWidth=2))
                
                # Draw connections to adjacent coils
                if phase.isupper():
                    # Positive direction - connect to next slot of same phase going down-right
                    _draw_coil_connection(drawing, exit_x, y, coil_span, slot_height, 
                                         color, going_right=True, num_slots=num_slots,
                                         num_poles=num_poles, slot_idx=i)
                else:
                    # Negative direction - connect going down-left
                    _draw_coil_connection(drawing, entry_x, y, coil_span, slot_height,
                                         color, going_right=False, num_slots=num_slots,
                                         num_poles=num_poles, slot_idx=i)
                
                # Direction arrow
                arrow_x = center_x + (15 if phase.isupper() else -15)
                arrow_dir = "→" if phase.isupper() else "←"
                drawing.add(String(arrow_x, y - 3, arrow_dir,
                                  fontSize=10, fontName='Helvetica',
                                  fillColor=color, textAnchor='middle'))
    
    # Show ellipsis if more slots
    if num_slots > 24:
        drawing.add(String(center_x, 20, f"... ({num_slots - 24} more slots)",
                          fontSize=8, fontName='Helvetica',
                          fillColor=colors.HexColor('#888888'), textAnchor='middle'))
    
    return drawing


def _draw_coil_connection(drawing: Drawing, x: float, y: float, span: float,
                          slot_height: float, color, going_right: bool,
                          num_slots: int, num_poles: int, slot_idx: int):
    """Draw coil connection lines between slots."""
    # Calculate coil pitch (slots spanned)
    coil_pitch = num_slots // num_poles
    
    # Only draw if connection stays within visible area
    target_slot = slot_idx + coil_pitch
    if target_slot < min(num_slots, 24):
        y_target = y - coil_pitch * slot_height
        
        if going_right:
            # Curve to the right and down
            mid_x = x + span * 0.3
            drawing.add(Line(x, y, mid_x, y - slot_height * 0.3, 
                           strokeColor=color, strokeWidth=1.5))
            drawing.add(Line(mid_x, y - slot_height * 0.3, mid_x, y_target + slot_height * 0.3,
                           strokeColor=color, strokeWidth=1.5))
        else:
            # Curve to the left and down
            mid_x = x - span * 0.3
            drawing.add(Line(x, y, mid_x, y - slot_height * 0.3,
                           strokeColor=color, strokeWidth=1.5))
            drawing.add(Line(mid_x, y - slot_height * 0.3, mid_x, y_target + slot_height * 0.3,
                           strokeColor=color, strokeWidth=1.5))


def create_winding_layout_section(num_slots: int, num_poles: int) -> tuple:
    """
    Create complete winding layout visualizations for PDF inclusion.
    
    Args:
        num_slots: Number of stator slots
        num_poles: Number of magnetic poles
    
    Returns:
        Tuple of (winding_info dict, circular_drawing, linear_drawing)
    """
    try:
        winding_info = generate_winding_schema(num_slots, num_poles)
        circular = create_circular_stator_drawing(winding_info, size=240)
        linear = create_linear_slot_diagram(winding_info, width=480, slot_height=25)
        return winding_info, circular, linear
    except ValueError as e:
        # Return None for invalid configurations
        return None, None, None


# For standalone testing
if __name__ == "__main__":
    # Test with common configurations
    test_configs = [
        (12, 10),  # 12 slots, 10 poles
        (12, 14),  # 12 slots, 14 poles
        (9, 6),    # 9 slots, 6 poles
        (18, 16),  # 18 slots, 16 poles
        (36, 12),  # 36 slots, 12 poles (distributed)
    ]
    
    for slots, poles in test_configs:
        print(f"\n{'='*50}")
        print(f"Configuration: {slots} slots, {poles} poles")
        print('='*50)
        try:
            info = generate_winding_schema(slots, poles)
            print(f"Schema: {info['schema_display']}")
            print(f"Distributed: {info['distributed']}")
            print(f"Balanced: {info['balanced']}")
            print(f"Cogging steps: {info['cogging_steps']}")
        except ValueError as e:
            print(f"Error: {e}")
