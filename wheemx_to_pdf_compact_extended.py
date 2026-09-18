#!/usr/bin/env python3
"""
WheemX Simulation Output to Compact PDF Datasheet Converter

CLI tool to convert WheemX JSON simulation output files to compact one-page PDF datasheets.
"""

import json
import math
import sys
from pathlib import Path
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Optional imports for STEP file rendering
try:
    import cadquery as cq
    HAS_CADQUERY = True
except ImportError:
    HAS_CADQUERY = False

# Register Space Grotesk fonts
FONT_DIR = Path(__file__).parent / "fonts"
IMAGES_DIR = Path(__file__).parent / "images"
STEP_FILES_DIR = Path(__file__).parent / "step_files"
pdfmetrics.registerFont(TTFont('SpaceGrotesk', FONT_DIR / 'SpaceGrotesk-Regular.ttf'))
pdfmetrics.registerFont(TTFont('SpaceGrotesk-Bold', FONT_DIR / 'SpaceGrotesk-Bold.ttf'))

# Register a font that supports Unicode symbols (Ω, √, µ)
# Try DejaVu Sans first, then fall back to Windows Arial
DEJAVU_PATH = FONT_DIR / 'DejaVuSans.ttf'
ARIAL_PATH = Path('C:/Windows/Fonts/arial.ttf')
if DEJAVU_PATH.exists():
    pdfmetrics.registerFont(TTFont('SymbolFont', DEJAVU_PATH))
    SYMBOL_FONT = 'SymbolFont'
elif ARIAL_PATH.exists():
    pdfmetrics.registerFont(TTFont('SymbolFont', ARIAL_PATH))
    SYMBOL_FONT = 'SymbolFont'
else:
    SYMBOL_FONT = 'Helvetica'


def create_page_footer(is_confidential: bool = False):
    """Create a page footer function with confidential flag."""
    def add_page_footer(canvas, doc):
        """Add logo, confidential mark, and page number to each page."""
        canvas.saveState()
        page_width, page_height = A4
        # Draw logo with clickable link
        logo_path = IMAGES_DIR / "wheemo_logo.png"
        logo_x = doc.leftMargin
        logo_y = 8*mm
        logo_w = 25*mm
        logo_h = 8*mm
        if logo_path.exists():
            canvas.drawImage(
                str(logo_path),
                logo_x, logo_y,
                width=logo_w, height=logo_h,
                preserveAspectRatio=True,
                mask='auto'
            )
            # Add clickable link over logo area
            url = "https://www.wheemo.dev?utm_source=datasheet&utm_medium=pdf"
            canvas.linkURL(url, (logo_x, logo_y, logo_x + logo_w, logo_y + logo_h))
        # Draw confidential mark in center (red)
        if is_confidential:
            canvas.setFont('SpaceGrotesk-Bold', 9)
            canvas.setFillColor(colors.HexColor('#cc0000'))
            canvas.drawCentredString(page_width / 2, 10*mm, "CONFIDENTIAL")
        canvas.setFont('SpaceGrotesk', 9)
        canvas.setFillColor(colors.HexColor('#666666'))
        canvas.drawRightString(page_width - doc.rightMargin, 10*mm,
                               f"Page {doc.page}")
        canvas.restoreState()
    return add_page_footer


def load_json(filepath: str) -> dict:
    """Load and parse JSON simulation output file."""
    with open(filepath, 'r') as f:
        return json.load(f)


def render_step_files_to_image(output_path: str, width: int = 800, height: int = 600,
                               timeout_seconds: int = 120,
                               step_files_dir: Path = None) -> bool:
    """
    Load all STEP files from step_files folder, merge them, and render to PNG.
    Returns True if successful, False otherwise.
    """
    import time

    search_dir = step_files_dir if step_files_dir is not None else STEP_FILES_DIR

    print("\n[3D Model] Starting STEP file rendering...")

    if not HAS_CADQUERY:
        print("[3D Model] ERROR: cadquery not installed. Skipping 3D rendering.")
        return False

    if not search_dir.exists():
        print(f"[3D Model] ERROR: step_files folder not found at {search_dir}")
        return False

    # Get unique STEP files (avoid duplicates)
    step_files_set = set()
    for pattern in ["*.step", "*.STEP", "*.stp", "*.STP"]:
        for f in search_dir.glob(pattern):
            step_files_set.add(f)
    step_files = sorted(list(step_files_set), key=lambda x: x.name)

    if not step_files:
        print("[3D Model] ERROR: No STEP files found in step_files folder.")
        return False

    print(f"[3D Model] Found {len(step_files)} unique STEP file(s):")
    for sf in step_files:
        print(f"  - {sf.name}")

    # Step 1: Import and combine STEP files
    try:
        print("[3D Model] Loading STEP files...")
        combined = None
        for step_file in step_files:
            print(f"  Loading: {step_file.name}...")
            shape = cq.importers.importStep(str(step_file))
            if combined is None:
                combined = shape
            else:
                combined = combined.add(shape)

        if combined is None:
            print("[3D Model] ERROR: Failed to load any shapes from STEP files.")
            return False
        print("[3D Model] All STEP files loaded successfully.")
    except Exception as e:
        print(f"[3D Model] ERROR loading STEP files: {type(e).__name__}: {e}")
        return False

    # Step 2: Export to SVG (with timeout and progress)
    svg_path = output_path.replace('.png', '.svg')
    try:
        print(f"[3D Model] Exporting to SVG (timeout: {timeout_seconds}s)...")
        print("[3D Model] This may take a while for complex geometry...")
        from cadquery import exporters
        import concurrent.futures

        def do_svg_export():
            exporters.export(
                combined,
                svg_path,
                exportType='SVG',
                opt={
                    "width": width,
                    "height": height,
                    "marginLeft": 10,
                    "marginTop": 10,
                    "projectionDir": (-1, -1, 1),
                    "showAxes": False,
                    "showHidden": False,
                }
            )

        # Run export with timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(do_svg_export)
            start_time = time.time()
            while not future.done():
                elapsed = int(time.time() - start_time)
                print(f"\r[3D Model] Exporting... {elapsed}s", end="", flush=True)
                try:
                    future.result(timeout=1)
                except concurrent.futures.TimeoutError:
                    if elapsed >= timeout_seconds:
                        print("\n[3D Model] ERROR: SVG export timed out")
                        return False
            print()

        future.result()

        if not Path(svg_path).exists():
            print(f"[3D Model] ERROR: SVG file was not created at {svg_path}")
            return False
        print(f"[3D Model] SVG exported: {svg_path}")
    except concurrent.futures.TimeoutError:
        print("\n[3D Model] ERROR: SVG export timed out")
        return False
    except Exception as e:
        print(f"\n[3D Model] ERROR exporting SVG: {type(e).__name__}: {e}")
        return False

    # Step 3: Convert SVG to PNG
    try:
        print("[3D Model] Converting SVG to PNG...")
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM

        time.sleep(0.1)

        drawing = svg2rlg(svg_path)
        if drawing is None:
            print(f"[3D Model] ERROR: Failed to parse SVG file: {svg_path}")
            return False

        renderPM.drawToFile(drawing, output_path, fmt="PNG")

        time.sleep(0.1)
        if not Path(output_path).exists():
            print(f"[3D Model] ERROR: PNG file was not created at {output_path}")
            return False

        print(f"[3D Model] PNG exported: {output_path}")

        try:
            Path(svg_path).unlink(missing_ok=True)
        except Exception:
            pass

        print("[3D Model] Rendering complete!")
        return True

    except ImportError as e:
        print(f"[3D Model] ERROR: Missing dependency for PNG conversion: {e}")
        return False
    except Exception as e:
        print(f"[3D Model] ERROR converting to PNG: {type(e).__name__}: {e}")
        return False


def calculate_turns(data: dict) -> float:
    """
    Calculate the maximum Number of Turns per Tooth.
    turns = DCSupplyVoltage / PeakLineToLineTerminalVoltage_SVM_V
    """
    dc_supply = data["Simulation"]["DCSupplyVoltage"]
    peak_voltage = data["Simulation"]["Output"]["PeakLineToLineTerminalVoltage_SVM_V"]
    return dc_supply / peak_voltage


def extract_values(data: dict, turns: float, safety_factor: float,
                   parallel_paths: int = 1) -> dict:
    """Extract values from JSON and convert them based on Number of Turns per Tooth."""
    output = data["Simulation"]["Output"]
    geom = data["Machine"]["GeometricalParameters"]
    sim_input = data["Simulation"]

    # Apply parallel paths to get final turns (same as main script)
    final_turns = int(math.floor(turns * parallel_paths)) / parallel_paths

    # Geometric values
    machine_outer_diameter_mm = geom["MachineOuterRadius"] * 2 * 1000
    machine_inner_diameter_mm = geom["MachineInnerRadius"] * 2 * 1000
    machine_thickness_mm = geom["MachineThickness"] * 1000
    dc_supply_voltage_v = sim_input["DCSupplyVoltage"]

    # Mass Properties
    machine_mass_kg = output["MassMachine_Kg"]
    rotor_mass_kg = (
        output.get("MassMagnetPerMachine_Kg", 0) +
        output.get("MassXPerMachine_Kg", 0) +
        output.get("MassRotorBackironPerMachine_Kg", 0)
    )
    stator_mass_kg = (
        output.get("MassToothPerMachine_Kg", 0) +
        output.get("MassCopperInclFillFactorPerMachine_Kg", 0) +
        output.get("MassPoleshoePerMachine_Kg", 0) +
        output.get("MassStatorBackironPerMachine_Kg", 0)
    )
    moment_of_inertia_g_cm2 = output["MomentOfInertiaRotor_KgM2"] * 1e7
    has_rotor_structure = data["Machine"].get("RotorStructure", False)

    # Losses
    total_losses_w = output["TotalLoss_W"] * (safety_factor ** 2)
    resistive_losses_w = output["StatorWindingResistanceLoss_W"] * (safety_factor ** 2)

    # Current - scales inversely with turns (RMS supply current)
    supply_current_rms_a = output["RmsSupplyCurrent_A"] / final_turns

    # BackEMF constant - scales with turns
    ke_phase_peak_v_per_rpm = output["BackEmfConstantPhasePeakKe_VPerRpm"] * final_turns
    ke_ll_peak_v_per_rpm = ke_phase_peak_v_per_rpm * math.sqrt(3)

    # Motor constant (resistance-based)
    motor_constant_km = (output["TotalTorque_Nm"] /
                         math.sqrt(resistive_losses_w) / safety_factor)

    # Torque constant (peak, from flux linkage or optimal no-load)
    kt_nm_per_a = output.get("TorqueConstantOptimalNoLoadKt_NmPerA")
    if kt_nm_per_a is None:
        kt_nm_per_a = output["TorqueConstantKtFromFluxLinkage_NmPerA"]
    kt_peak_nm_per_a = kt_nm_per_a * final_turns / safety_factor

    # Inductances - scale with turns^2
    ld_uh = output["DAxisInductanceLd_uH"] * (final_turns ** 2)
    lq_uh = output["QAxisInductanceLq_uH"] * (final_turns ** 2)
    terminal_inductance_uh = ld_uh + lq_uh

    # Torque
    torque_nm = output["TotalTorque_Nm"]
    torque_ripple_percent = output["TorqueRipple_Percent"]

    # Speed and phase resistance
    speed_rpm = sim_input["RPM"]
    phase_resistance_ohm = output["ResistanceMachinePhase_Ohm"] * (final_turns ** 2)

    # No load speed: V_phase / Ke where V_phase = V_dc / sqrt(3)
    no_load_speed_rpm = dc_supply_voltage_v / math.sqrt(3) / ke_phase_peak_v_per_rpm

    return {
        "machine_outer_diameter_mm": machine_outer_diameter_mm,
        "machine_inner_diameter_mm": machine_inner_diameter_mm,
        "machine_thickness_mm": machine_thickness_mm,
        "dc_supply_voltage_v": dc_supply_voltage_v,
        "machine_mass_kg": machine_mass_kg,
        "rotor_mass_kg": rotor_mass_kg,
        "stator_mass_kg": stator_mass_kg,
        "moment_of_inertia_g_cm2": moment_of_inertia_g_cm2,
        "has_rotor_structure": has_rotor_structure,
        "total_losses_w": total_losses_w,
        "resistive_losses_w": resistive_losses_w,
        "supply_current_rms_a": supply_current_rms_a,
        "ke_phase_peak_v_per_rpm": ke_phase_peak_v_per_rpm,
        "ke_ll_peak_v_per_rpm": ke_ll_peak_v_per_rpm,
        "motor_constant_km": motor_constant_km,
        "kt_peak_nm_per_a": kt_peak_nm_per_a,
        "ld_uh": ld_uh,
        "lq_uh": lq_uh,
        "terminal_inductance_uh": terminal_inductance_uh,
        "torque_nm": torque_nm,
        "torque_ripple_percent": torque_ripple_percent,
        "speed_rpm": speed_rpm,
        "phase_resistance_ohm": phase_resistance_ohm,
        "no_load_speed_rpm": no_load_speed_rpm,
        "final_turns": final_turns,
    }


def format_mass(mass_kg):
    """Format mass: use kg if >= 1kg, otherwise g."""
    mass_g = mass_kg * 1000
    if mass_g >= 1000:
        return f"{mass_kg:.2f}", "kg"
    return f"{mass_g:.1f}", "g"


def format_moment_of_inertia(inertia_g_cm2):
    """Format moment of inertia: use kg·m² if >= 10000 g·cm², otherwise g·cm²."""
    if inertia_g_cm2 >= 10000:
        inertia_kg_m2 = inertia_g_cm2 / 10000000
        return f"{inertia_kg_m2:.4f}", "kg·m²"
    return f"{inertia_g_cm2:.1f}", "g·cm²"


def format_torque(torque_nm):
    """Format torque: use Nm if >= 1Nm, otherwise mNm."""
    torque_mnm = torque_nm * 1000
    if torque_mnm >= 1000:
        return f"{torque_nm:.2f}", "Nm"
    return f"{torque_mnm:.1f}", "mNm"


def format_motor_constant(km):
    """Format motor constant."""
    km_mnm = km * 1000
    if km_mnm >= 1000:
        return f"{km:.2f}", "Nm/√W"
    return f"{km_mnm:.1f}", "mNm/√W"


def format_torque_constant(kt):
    """Format torque constant."""
    kt_mnm = kt * 1000
    if kt_mnm >= 1000:
        return f"{kt:.2f}", "Nm/A"
    return f"{kt_mnm:.1f}", "mNm/A"


def scale_torque_and_losses(values: dict, new_torque: float,
                            original_torque: float) -> dict:
    """Scale torque and dependent values, keeping resistive/total loss ratio."""
    k = new_torque / original_torque
    values['torque_nm'] = new_torque
    values['supply_current_rms_a'] = values['supply_current_rms_a'] * k
    original_resistive = values['resistive_losses_w']
    original_total = values['total_losses_w']
    resistive_ratio = original_resistive / original_total
    new_resistive = original_resistive * (k ** 2)
    new_total = new_resistive / resistive_ratio
    values['resistive_losses_w'] = new_resistive
    values['total_losses_w'] = new_total
    return values


def generate_compact_pdf(values: dict, peak_torque_nm: float, temp_range: tuple,
                         output_path: str, motor_name: str = "",
                         is_confidential: bool = False,
                         source_folder: Path = None):
    """Generate a compact one-page PDF datasheet."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=15*mm,
        leftMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=20*mm
    )

    # Styles
    title_style = ParagraphStyle(
        'Title', fontName='SpaceGrotesk-Bold', fontSize=16,
        textColor=colors.HexColor('#1abb0e'), spaceAfter=10
    )
    section_style = ParagraphStyle(
        'Section', fontName='SpaceGrotesk-Bold', fontSize=10,
        textColor=colors.HexColor('#333333'), spaceAfter=4, spaceBefore=8
    )

    elements = []

    # Title - green prefix, black motor name
    display_name = motor_name.replace('_', ' ') if motor_name else ""
    if display_name:
        title_html = (f'<font color="#1abb0e">Motor Datasheet: </font>'
                      f'<font color="#222222">{display_name}</font>')
    else:
        title_html = '<font color="#1abb0e">Motor Datasheet</font>'
    elements.append(Paragraph(title_html, title_style))
    elements.append(Spacer(1, 4))

    # Helper to create compact table
    def create_table(data):
        table = Table(data, colWidths=[95*mm, 35*mm, 25*mm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#222222')),
            ('FONTNAME', (0, 0), (-1, 0), 'SpaceGrotesk-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTNAME', (0, 1), (1, -1), 'SpaceGrotesk'),
            ('FONTNAME', (2, 0), (2, -1), SYMBOL_FONT),  # Unit column uses symbol font
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#1abb0e')),
            ('LINEBELOW', (0, 1), (-1, -2), 0.5, colors.HexColor('#eeeeee')),
        ]))
        return table

    # Machine Configuration Section
    elements.append(Paragraph("Machine Configuration", section_style))
    config_data = [
        ["Parameter", "Value", "Unit"],
        ["Machine Outer Diameter", f"{values['machine_outer_diameter_mm']:.1f}", "mm"],
        ["Machine Length / Thickness", f"{values['machine_thickness_mm']:.1f}", "mm"],
        ["Voltage", f"{values['dc_supply_voltage_v']:.1f}", "V"],
        ["Operating Temperature", f"{temp_range[0]} to {temp_range[1]}", "°C"],
    ]
    elements.append(create_table(config_data))
    elements.append(Spacer(1, 6))

    # Mass Properties Section
    elements.append(Paragraph("Mass Properties", section_style))
    machine_mass_val, machine_mass_unit = format_mass(values['machine_mass_kg'])
    rotor_mass_val, rotor_mass_unit = format_mass(values['rotor_mass_kg'])
    stator_mass_val, stator_mass_unit = format_mass(values['stator_mass_kg'])
    rotor_structure_included = "Yes" if values['has_rotor_structure'] else "No"
    
    inertia_label = "Rotor Moment of Inertia"
    if values['has_rotor_structure']:
        inertia_label += " (incl. simplified structure)"
    inertia_val, inertia_unit = format_moment_of_inertia(values['moment_of_inertia_g_cm2'])

    mass_data = [
        ["Parameter", "Value", "Unit"],
        ["Machine Mass (active components only)", machine_mass_val, machine_mass_unit],
        ["Rotor Mass", rotor_mass_val, rotor_mass_unit],
        ["Stator Mass", stator_mass_val, stator_mass_unit],
        ["Rotor Structure Included", rotor_structure_included, "-"],
        [inertia_label, inertia_val, inertia_unit],
    ]
    elements.append(create_table(mass_data))
    elements.append(Spacer(1, 6))

    # Performance Metrics Section
    elements.append(Paragraph("Performance Metrics", section_style))
    cont_torque_val, cont_torque_unit = format_torque(values['torque_nm'])
    peak_torque_val, peak_torque_unit = format_torque(peak_torque_nm)
    km_val, km_unit = format_motor_constant(values['motor_constant_km'])
    kt_val, kt_unit = format_torque_constant(values['kt_peak_nm_per_a'])
    ke_phase = values['ke_phase_peak_v_per_rpm'] * 1000
    ke_ll = values['ke_ll_peak_v_per_rpm'] * 1000
    perf_data = [
        ["Parameter", "Value", "Unit"],
        ["Torque (continuous)", cont_torque_val, cont_torque_unit],
        # ["Torque (peak)", peak_torque_val, peak_torque_unit],
        ["Speed", f"{values['speed_rpm']:.0f}", "rpm"],
        # ["No Load Speed", f"{values['no_load_speed_rpm']:.0f}", "rpm"],
        ["Losses (continuous)", f"{values['total_losses_w']:.1f}", "W"],
        ["Supply Current (RMS)", f"{values['supply_current_rms_a']:.2f}", "A"],
        ["Phase Resistance (per phase)", f"{values['phase_resistance_ohm']*1000:.1f}", "mΩ"],
        ["Terminal Inductance (Ltt = Ld + Lq)", f"{values['terminal_inductance_uh']:.1f}", "µH"],
        ["D-axis Inductance (Ld)", f"{values['ld_uh']:.1f}", "µH"],
        ["Ke (peak, phase)", f"{ke_phase:.2f}", "mV/rpm"],
        ["Ke (peak, line-to-line)", f"{ke_ll:.2f}", "mV/rpm"],
        ["Kt (peak)", kt_val, kt_unit],
        ["Motor Constant (Km)", km_val, km_unit],
    ]
    elements.append(create_table(perf_data))
    elements.append(Spacer(1, 8))

    # 3D Model Section (if STEP files are available)
    model_image_path = str(IMAGES_DIR / "motor_3d_view.png")
    if render_step_files_to_image(model_image_path, width=600, height=450,
                                   step_files_dir=source_folder):
        elements.append(Paragraph("3D Model", section_style))
        elements.append(Image(model_image_path, width=80*mm, height=60*mm))
        elements.append(Spacer(1, 6))

    # Operating Curve Section (if image exists)
    operating_curve_path = Path(__file__).parent / "opearting_curve" / "image.png"
    if operating_curve_path.exists():
        elements.append(Paragraph("Operating Curve", section_style))
        # Get actual image dimensions and scale to fit while preserving ratio
        with PILImage.open(operating_curve_path) as pil_img:
            orig_w, orig_h = pil_img.size
        max_width = 140 * mm
        max_height = 90 * mm
        scale = min(max_width / orig_w, max_height / orig_h)
        elements.append(Image(
            str(operating_curve_path),
            width=orig_w * scale,
            height=orig_h * scale
        ))

    footer_func = create_page_footer(is_confidential)
    doc.build(elements, onFirstPage=footer_func, onLaterPages=footer_func)


def main():
    print("=" * 60)
    print("  WheemX Compact Datasheet Generator")
    print("=" * 60)

    if len(sys.argv) > 1:
        input_arg = sys.argv[1]
    else:
        input_arg = input("Enter the path to the source folder: ").strip()
        if input_arg.startswith('"') and input_arg.endswith('"'):
            input_arg = input_arg[1:-1]

    input_path = Path(input_arg)
    if not input_path.exists():
        print(f"\nError: Path not found: {input_path}")
        sys.exit(1)

    # Resolve source folder and JSON file
    if input_path.is_dir():
        source_folder = input_path
        json_candidates = sorted(source_folder.glob("*output.json"))
        if not json_candidates:
            print(f"Error: No *output.json file found in {source_folder}")
            sys.exit(1)
        json_path = json_candidates[-1]
        motor_name = source_folder.name
    else:
        json_path = input_path
        source_folder = None
        motor_name = input_path.stem

    print(f"\nLoading: {json_path.name}")
    data = load_json(str(json_path))
    turns = calculate_turns(data)

    dc_voltage = data["Simulation"]["DCSupplyVoltage"]
    peak_voltage = data["Simulation"]["Output"]["PeakLineToLineTerminalVoltage_SVM_V"]

    print(f"\n  DC Supply Voltage: {dc_voltage} V")
    print(f"  Peak Line-to-Line Terminal Voltage (SVM): {peak_voltage:.4f} V")
    print(f"  Calculated Number of Turns per Tooth: {turns}")

    # Ask for safety factor
    print("\n" + "-" * 40)
    while True:
        response = input("Safety factor?: ").strip()
        try:
            safety_factor = float(response)
            break
        except ValueError:
            print("Please enter a valid number.")

    # Ask for parallel paths
    while True:
        response = input("Number of parallel paths?: ").strip()
        try:
            parallel_paths = int(response)
            break
        except ValueError:
            print("Please enter a valid integer.")

    # Extract values
    print("\nProcessing data...")
    values = extract_values(data, turns, safety_factor, parallel_paths)

    # Ask for continuous torque override
    original_torque = values['torque_nm']
    response = input(f"Continuous torque (current: {original_torque:.4f} Nm, Enter to keep): ").strip()
    if response:
        try:
            new_torque = float(response)
            if new_torque != original_torque:
                values = scale_torque_and_losses(values, new_torque, original_torque)
                print(f"  Scaled: {original_torque:.4f} -> {new_torque:.4f} Nm")
        except ValueError:
            print("Invalid value, keeping original.")

    # Ask for peak torque
    while True:
        response = input("Peak torque (Nm): ").strip()
        try:
            peak_torque_nm = float(response)
            break
        except ValueError:
            print("Please enter a valid number.")

    # Ask for operating temperature range
    temp_min = input("Operating temperature min (°C, default -40): ").strip()
    temp_min = int(temp_min) if temp_min else -40
    temp_max = input("Operating temperature max (°C, default 85): ").strip()
    temp_max = int(temp_max) if temp_max else 85
    temp_range = (temp_min, temp_max)

    # Ask if confidential
    conf_response = input("Mark as confidential? (y/n, default n): ").strip().lower()
    is_confidential = conf_response in ['y', 'yes']

    # Generate output filename (use folder name / stem as motor name)
    output_filename = motor_name + "_compact_datasheet.pdf"
    output_path = input_path.parent / output_filename

    # Generate PDF
    print(f"\nGenerating PDF: {output_filename}")
    generate_compact_pdf(values, peak_torque_nm, temp_range, str(output_path),
                         motor_name, is_confidential,
                         source_folder=source_folder)

    print(f"\n✓ Datasheet saved to: {output_path}")
    print()


if __name__ == "__main__":
    main()