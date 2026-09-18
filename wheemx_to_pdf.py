#!/usr/bin/env python3
"""
WheemX Simulation Output to PDF Datasheet Converter

CLI tool to convert WheemX JSON simulation output files to PDF datasheets.
"""

import json
import math
import sys
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.graphics.shapes import Drawing, Line, Polygon, String
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from winding_layout import create_winding_layout_section

# Optional imports for STEP file rendering
try:
    import cadquery as cq
    HAS_CADQUERY = True
except ImportError:
    HAS_CADQUERY = False

# Register Space Grotesk fonts
FONT_DIR = Path(__file__).parent / "fonts"
IMAGES_DIR = Path(__file__).parent / "images"
pdfmetrics.registerFont(TTFont('SpaceGrotesk', FONT_DIR / 'SpaceGrotesk-Regular.ttf'))
pdfmetrics.registerFont(TTFont('SpaceGrotesk-Bold', FONT_DIR / 'SpaceGrotesk-Bold.ttf'))


def create_page_footer(is_confidential: bool = False):
    """Create a page footer function with confidential flag."""
    def add_page_footer(canvas, doc):
        """Add logo, confidential mark, and page number to each page."""
        canvas.saveState()
        
        page_width, page_height = A4
        
        # Draw logo in bottom left with clickable link
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
        
        # Draw page number in bottom right
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


STEP_FILES_DIR = Path(__file__).parent / "step_files"


def _svg_export_subprocess(step_files_list, svg_out, w, h):
    """Run SVG export in isolated process to catch OpenCASCADE crashes.
    
    Must be at module level for Windows multiprocessing compatibility.
    """
    try:
        import cadquery as cq_proc
        from cadquery import exporters
        
        # Reload and combine shapes in this process
        combined_proc = None
        for step_path in step_files_list:
            shape = cq_proc.importers.importStep(step_path)
            if combined_proc is None:
                combined_proc = shape
            else:
                combined_proc = combined_proc.add(shape)
        
        # Export to SVG
        exporters.export(
            combined_proc,
            svg_out,
            exportType='SVG',
            opt={
                "width": w,
                "height": h,
                "marginLeft": 10,
                "marginTop": 10,
                "projectionDir": (-1, -1, 1),
                "showAxes": False,
                "showHidden": False,
            }
        )
    except Exception as e:
        print(f"[3D Model] Process error: {e}")
        raise


def render_step_files_to_image(output_path: str, width: int = 800, height: int = 600,
                               timeout_seconds: int = 120,
                               step_files_dir: Path = None) -> bool:
    """
    Load all STEP files from step_files folder, merge them, and render to PNG.
    Camera positioned with Y-axis up, isometric view.
    Returns True if successful, False otherwise.
    """
    import time

    search_dir = step_files_dir if step_files_dir is not None else STEP_FILES_DIR

    print("\n[3D Model] Starting STEP file rendering...")

    if not HAS_CADQUERY:
        print("[3D Model] ERROR: cadquery not installed. Skipping 3D rendering.")
        print("[3D Model] Install with: pip install cadquery-ocp")
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
    
    # Step 2: Export to SVG (with timeout and crash protection)
    # Use multiprocessing to isolate potential crashes in OpenCASCADE
    svg_path = output_path.replace('.png', '.svg')
    try:
        print(f"[3D Model] Exporting to SVG (timeout: {timeout_seconds}s)...")
        print("[3D Model] This may take a while for complex geometry...")
        import multiprocessing
        
        # Convert step_files to string paths for pickling
        step_files_list = [str(sf) for sf in step_files]
        
        # Run export in separate process (using module-level function for Windows)
        process = multiprocessing.Process(
            target=_svg_export_subprocess,
            args=(step_files_list, svg_path, width, height)
        )
        process.start()
        
        # Show progress while waiting
        start_time = time.time()
        while process.is_alive():
            elapsed = int(time.time() - start_time)
            print(f"\r[3D Model] Exporting... {elapsed}s", end="", flush=True)
            process.join(timeout=1)
            if elapsed >= timeout_seconds:
                process.terminate()
                process.join(timeout=5)
                print(f"\n[3D Model] ERROR: SVG export timed out after {timeout_seconds}s")
                print("[3D Model] Try simplifying the STEP files or increasing timeout.")
                return False
        print()  # New line after progress
        
        # Check if process crashed
        if process.exitcode != 0:
            print(f"[3D Model] ERROR: SVG export process crashed (exit code: {process.exitcode})")
            print("[3D Model] This may be due to complex geometry or OpenCASCADE issues.")
            return False
        
        # Verify SVG was created
        if not Path(svg_path).exists():
            print(f"[3D Model] ERROR: SVG file was not created at {svg_path}")
            return False
        print(f"[3D Model] SVG exported: {svg_path}")
    except Exception as e:
        print(f"\n[3D Model] ERROR exporting SVG: {type(e).__name__}: {e}")
        return False
    
    # Step 3: Convert SVG to PNG
    try:
        print("[3D Model] Converting SVG to PNG...")
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        
        # Give the file system a moment
        time.sleep(0.1)
        
        drawing = svg2rlg(svg_path)
        if drawing is None:
            print(f"[3D Model] ERROR: Failed to parse SVG file: {svg_path}")
            return False
        
        renderPM.drawToFile(drawing, output_path, fmt="PNG")
        
        # Verify PNG was created
        time.sleep(0.1)
        if not Path(output_path).exists():
            print(f"[3D Model] ERROR: PNG file was not created at {output_path}")
            return False
        
        print(f"[3D Model] PNG exported: {output_path}")
        
        # Clean up SVG file
        try:
            Path(svg_path).unlink(missing_ok=True)
        except Exception:
            pass  # Ignore cleanup errors
        
        print("[3D Model] Rendering complete!")
        return True
        
    except ImportError as e:
        print(f"[3D Model] ERROR: Missing dependency for PNG conversion: {e}")
        print("[3D Model] Install with: pip install svglib reportlab[renderPM]")
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


def count_stators_and_rotors(data: dict) -> tuple:
    """Count number of stators and rotors from ConfigurationSeparated."""
    config_sep = data["Machine"].get("ConfigurationSeparated", [])
    num_stators = sum(1 for layer in config_sep if "S" in layer)
    num_rotors = sum(1 for layer in config_sep if "R" in layer)
    return num_stators, num_rotors


def extract_and_convert_values(data: dict, turns: float, is_peak: bool, safety_factor: float, parallel_paths: int) -> dict:
    """
    Extract values from JSON and convert them based on Number of Turns per Tooth.
    
    Conversion rules:
    - Current: I_new = I_old / turns
    - Voltage/BackEMF: V_new = V_old * turns
    - Inductance: L_new = L_old * turns^2
    - Flux linkage: Ψ_new = Ψ_old * turns
    - Torque constant: Kt_new = Kt_old * turns
    - Motor constant: Km_new = Km_old * turns
    """
    output = data["Simulation"]["Output"]
    geom = data["Machine"]["GeometricalParameters"]
    rotor_geom = data["Rotor"]["GeometricalParameters"]["Magnets"]
    stator_geom = data["Stator"]["GeometricalParameters"]["Teeth"]
    sim_input = data["Simulation"]

    final_turns = int(math.floor(turns * parallel_paths)) / parallel_paths
    if 0:
        print("\nXXXXXXXXXXXXXXXXXXXXXXXX")
        print("\nCAUTION HARD CODED TURNS!")
        print("\nXXXXXXXXXXXXXXXXXXXXXXXX")
        final_turns = 20
    
    # ==========================================================================
    # CONFIGURATION
    # ==========================================================================
    num_stators, num_rotors = count_stators_and_rotors(data)
    has_rotor_structure = data["Machine"].get("RotorStructure", False)
    num_slots = data["Simulation"]["Property"]["num_of_slots"]
    num_phases = data["Simulation"]["NumberOfPhases"]
    coils_per_phase = num_slots // num_phases
    pole_pairs = rotor_geom["MagnetsNumber"] // 2
    
    # Turns per tooth designed = turns × parallel_paths
    turns_per_tooth_designed = final_turns * parallel_paths
    # Phase turns × number of stators (all phases in series)
    phase_turns = final_turns * coils_per_phase * num_stators
    
    # ==========================================================================
    # MATERIALS
    # ==========================================================================
    stator_material = data["Stator"]["PhysicalProperties"].get("TeethMaterial", "N/A")
    magnet_material = data["Rotor"]["PhysicalProperties"].get("MagnetsMaterial", "N/A")
    rotor_backiron_material = data["Rotor"]["PhysicalProperties"].get("BackIronMaterial", "N/A")
    coil_material = data["Stator"]["PhysicalProperties"].get("CoilMaterial", "N/A")
    
    # ==========================================================================
    # GEOMETRY (no conversion needed)
    # ==========================================================================
    machine_outer_diameter_mm = geom["MachineOuterRadius"] * 2 * 1000
    machine_inner_diameter_mm = geom["MachineInnerRadius"] * 2 * 1000
    machine_thickness_mm = geom["MachineThickness"] * 1000
    teeth_thickness_mm = stator_geom["TeethThickness"] * 1000
    airgap_mm = geom["AirGapThickness"] * 1000
    
    # Heights / Lengths (Fallback to machine thickness if not explicitly defined)
    stator_height_mm = data["Stator"]["GeometricalParameters"].get("StatorThickness", geom.get("MachineThickness", 0)) * 1000
    rotor_height_mm = data["Rotor"]["GeometricalParameters"].get("RotorThickness", geom.get("MachineThickness", 0)) * 1000
    magnet_height_mm = rotor_geom.get("MagnetsThickness", 0) * 1000

    # Coil/winding parameters
    fill_factor = sim_input.get("FillFactor")
    slot_fill_factor = output.get("SlotFillFactor")
    coil_params = data["Stator"]["GeometricalParameters"].get("Coil", {})
    
    # Slot width = CoilWidth * 2 + CoilAdjacentDistance
    coil_width = coil_params.get("CoilWidth")
    coil_adjacent = coil_params.get("CoilAdjacentDistance")
    coil_distance_topbot = coil_params.get("CoilBaseOffset")
    coil_distance_tooth = coil_params.get("CoilGapDistance")
    slot_width_mm = None
    available_coil_space_mm = None
    if coil_width is not None and coil_adjacent is not None:
        slot_width_mm = (coil_width * 2 + coil_adjacent) * 1000
        available_coil_space_mm = slot_width_mm / 2
    
    # Assumed coil width = WireWidthFinal
    assumed_coil_width_mm = None
    if coil_params.get("WireWidthFinal") is not None:
        assumed_coil_width_mm = coil_params["WireWidthFinal"] * 1000

    # Assumed coil height = TeethThickness - 2 * CoilBaseOffset
    assumed_coil_height_mm = None
    if coil_distance_topbot is not None and "TeethThickness" in stator_geom:
        assumed_coil_height_mm = (stator_geom["TeethThickness"] - 2 * coil_distance_topbot) * 1000
        
    # ==========================================================================
    # MASS PROPERTIES (no conversion needed)
    # ==========================================================================
    machine_mass_kg = output["MassMachine_Kg"]
    
    # Breakdown masses
    magnet_mass_kg = output.get("MassMagnetPerMachine_Kg", 0)
    copper_mass_kg = output.get("MassCopperPerMachine_Kg", output.get("MassCopperInclFillFactorPerMachine_Kg", 0))
    stator_steel_mass_kg = (
        output.get("MassToothPerMachine_Kg", 0) +
        output.get("MassPoleshoePerMachine_Kg", 0) +
        output.get("MassStatorBackironPerMachine_Kg", 0)
    )

    rotor_mass_kg = (
        magnet_mass_kg +
        output.get("MassXPerMachine_Kg", 0) +
        output.get("MassRotorBackironPerMachine_Kg", 0)
    )
    stator_mass_kg = (
        stator_steel_mass_kg +
        output.get("MassCopperInclFillFactorPerMachine_Kg", 0)
    )
    moment_of_inertia_g_cm2 = output["MomentOfInertiaRotor_KgM2"] * 1e7
    
    # ==========================================================================
    # OPERATING POINT
    # ==========================================================================
    dc_supply_voltage_v = sim_input["DCSupplyVoltage"]
    speed_rpm = sim_input["RPM"]
    magnet_temperature_c = sim_input.get("MagnetTemperature_C", 20.0)
    phase_advance_angle_deg = sim_input.get("PhaseAdvanceAngle_ElDeg", 0.0)
    frequency_hz = output["RotationalFrequencyElec_Hz"]
    omega_elec = 2 * math.pi * frequency_hz  # rad/s electrical
    
    # ==========================================================================
    # LOSSES
    # ==========================================================================
    total_losses_w = output["TotalLoss_W"]
    resistive_losses_w = output["StatorWindingResistanceLoss_W"]
    iron_core_loss_w = output.get("TotalIronCoreLoss_W", 0.0)
    magnet_eddy_loss_w = output.get("MagnetEddyCurrentLoss_W", 0.0)
    rotor_structure_eddy_loss_w = output.get("RotorStructureEddyCurrentLoss_W", 0.0)
    winding_eddy_loss_w = output.get("WindingEddyCurrentLoss_W", 0.0)
    
    # ==========================================================================
    # ELECTRICAL - CURRENT (scales inversely with turns)
    # ==========================================================================
    peak_current_a = output["PeakSupplyCurrent_A"] / final_turns
    rms_current_a = output["RmsSupplyCurrent_A"] / final_turns
    
    # Id and Iq from phase advance angle
    # PhaseAdvanceAngle is positively defined; for negative Id, switch sign
    phase_advance_rad = math.radians(phase_advance_angle_deg)
    id_peak_a = -peak_current_a * math.sin(phase_advance_rad)  # negative for field weakening
    iq_peak_a = peak_current_a * math.cos(phase_advance_rad)
    
    # ==========================================================================
    # ELECTRICAL - RESISTANCE & INDUCTANCE (scale with turns^2)
    # ==========================================================================
    phase_resistance_ohm = output["ResistanceMachinePhase_Ohm"] * (final_turns ** 2)
    ld_uh = output["DAxisInductanceLd_uH"] * (final_turns ** 2)
    lq_uh = output["QAxisInductanceLq_uH"] * (final_turns ** 2)
    ltt_uh = ld_uh + lq_uh  # Terminal inductance
    
    # ==========================================================================
    # ELECTRICAL - FLUX & BACK-EMF (scale with turns)
    # ==========================================================================
    pm_flux_linkage_mwb = output["PermanentMagnetFluxLinkageLoad_mWb"] * final_turns / safety_factor
    ke_v_per_rpm = output["BackEmfConstantPhasePeakKe_VPerRpm"] * final_turns

    try:
        if ke_v_per_rpm == 0.0:
            ke_v_per_rpm = output["BackEmfConstantOptimalNoLoadPhasePeakKe_VPerRpm"] * final_turns
    except:
        ke_v_per_rpm = 0.0
    
    # Back-EMF voltages at operating point (scale with turns)
    # Some JSON files may not have these values, calculate from Ke if missing
    peak_phase_backemf_raw = output.get("PeakPhaseBackEmf_V")
    if peak_phase_backemf_raw is not None:
        peak_phase_backemf_v = peak_phase_backemf_raw * final_turns
    else:
        # Calculate from Ke_phase_peak: V_emf = Ke_phase_peak * rpm * turns
        ke_phase_peak = output["BackEmfConstantPhasePeakKe_VPerRpm"]
        peak_phase_backemf_v = ke_phase_peak * speed_rpm * final_turns
    
    peak_ll_backemf_raw = output.get("PeakLineToLineBackEmf_V")
    if peak_ll_backemf_raw is not None:
        peak_ll_backemf_v = peak_ll_backemf_raw * final_turns
    else:
        # Calculate from Ke_LL_rms: V_emf_LL_peak = Ke_LL_rms * rpm * sqrt(2) * turns
        ke_ll_rms = output["BackEmfConstantLineToLineRmsKe_VPerRpm"]
        peak_ll_backemf_v = ke_ll_rms * speed_rpm * math.sqrt(2) * final_turns
    
    # ==========================================================================
    # VOLTAGE BREAKDOWN (at operating point with integer turns)
    # ==========================================================================
    # Convert inductances to H for calculations
    ld_h = ld_uh * 1e-6
    lq_h = lq_uh * 1e-6
    
    # Resistive voltage drop: V_R = I * R (in phase with current)
    v_resistive_phase_peak = peak_current_a * phase_resistance_ohm
    
    # Inductive voltage drops (90° ahead of respective currents)
    # V_Ld = ω * Ld * Id, V_Lq = ω * Lq * Iq
    v_ld_peak = omega_elec * ld_h * abs(id_peak_a)
    v_lq_peak = omega_elec * lq_h * abs(iq_peak_a)
    v_inductive_total_peak = math.sqrt(v_ld_peak**2 + v_lq_peak**2)
    
    # Back-EMF voltage (from simulation)
    v_backemf_phase_peak = peak_phase_backemf_v
    
    # Terminal voltage from simulation (for reference)
    v_terminal_phase_raw = output.get("PeakPhaseTerminalVoltage_V")
    if v_terminal_phase_raw is not None:
        v_terminal_phase_peak = v_terminal_phase_raw * final_turns
    else:
        # Approximate: sqrt(V_emf^2 + V_R^2 + V_L^2) - simplified
        v_terminal_phase_peak = math.sqrt(
            v_backemf_phase_peak**2 + v_resistive_phase_peak**2 +
            v_inductive_total_peak**2
        )
    v_terminal_ll_peak = output["PeakLineToLineTerminalVoltage_SVM_V"] * final_turns
    
    # Line-to-line conversions (multiply by sqrt(3) for wye connection)
    v_resistive_ll_peak = v_resistive_phase_peak * math.sqrt(3)
    v_inductive_ll_peak = v_inductive_total_peak * math.sqrt(3)
    v_backemf_ll_peak = peak_ll_backemf_v
    
    # ==========================================================================
    # PERFORMANCE CONSTANTS
    # ==========================================================================
    motor_constant_nm_per_sqrt_w = output["MotorConstantKm_NmPerSqrtW"] / safety_factor
    motor_constant_nm_per_sqrt_w_resistance = output["TotalTorque_Nm"] / math.sqrt(output["StatorWindingResistanceLoss_W"]) / safety_factor
    
    kt_nm_per_a = output.get("TorqueConstantOptimalNoLoadKt_NmPerA")
    if kt_nm_per_a is None:
        kt_nm_per_a = output["TorqueConstantKtFromFluxLinkage_NmPerA"]
    kt_nm_per_a = kt_nm_per_a * final_turns / safety_factor
    
    # ==========================================================================
    # TORQUE & SATURATION
    # ==========================================================================
    torque_nm = output["TotalTorque_Nm"]
    torque_ripple_percent = output["TorqueRipple_Percent"]
    
    saturation_percent = output["Saturation_Percent"]
    if saturation_percent is None:
        saturation_percent = 0.0
    if saturation_percent < 0:
        saturation_percent = 0.0
    
    # Power factor (no conversion needed)
    power_factor = output.get("PowerFactor", None)
    
    # ==========================================================================
    # MECHANICAL FORCES (no conversion needed)
    # ==========================================================================
    airgap_axial_force_avg_n = output.get("AirgapAxialForceAverage_N")
    magnet_axial_force_pos_max_n = output.get("MagnetAxialForcePositiveMaximum_N")
    magnet_axial_force_pos_min_n = output.get("MagnetAxialForcePositiveMinimum_N")
    magnet_axial_force_neg_max_n = output.get("MagnetAxialForceNegativeMaximum_N")
    magnet_axial_force_neg_min_n = output.get("MagnetAxialForceNegativeMinimum_N")
    magnet_radial_force_pos_max_n = output.get("MagnetRadialForcePositiveMaximum_N")
    magnet_radial_force_neg_max_n = output.get("MagnetRadialForceNegativeMaximum_N")
    
    return {
        # Configuration
        "num_stators": num_stators,
        "num_rotors": num_rotors,
        "num_slots": num_slots,
        "pole_pairs": pole_pairs,
        "parallel_paths": parallel_paths,
        "turns_per_tooth_designed": turns_per_tooth_designed,
        "phase_turns": phase_turns,
        "turns": turns,
        "final_turns": final_turns,
        "is_peak": is_peak,
        "has_rotor_structure": has_rotor_structure,
        # Materials
        "stator_material": stator_material,
        "magnet_material": magnet_material,
        "rotor_backiron_material": rotor_backiron_material,
        "coil_material": coil_material,
        # Geometry
        "machine_outer_diameter_mm": machine_outer_diameter_mm,
        "machine_inner_diameter_mm": machine_inner_diameter_mm,
        "machine_thickness_mm": machine_thickness_mm,
        "stator_height_mm": stator_height_mm,
        "rotor_height_mm": rotor_height_mm,
        "magnet_height_mm": magnet_height_mm,
        "teeth_thickness_mm": teeth_thickness_mm,
        "airgap_mm": airgap_mm,
        "fill_factor": fill_factor,
        "slot_fill_factor": slot_fill_factor,
        "slot_width_mm": slot_width_mm,
        "available_coil_space_mm": available_coil_space_mm,
        "assumed_coil_width_mm": assumed_coil_width_mm,
        "assumed_coil_height_mm": assumed_coil_height_mm,
        # Mass
        "machine_mass_kg": machine_mass_kg,
        "rotor_mass_kg": rotor_mass_kg,
        "stator_mass_kg": stator_mass_kg,
        "copper_mass_kg": copper_mass_kg,
        "stator_steel_mass_kg": stator_steel_mass_kg,
        "magnet_mass_kg": magnet_mass_kg,
        "moment_of_inertia_g_cm2": moment_of_inertia_g_cm2,
        # Operating point
        "dc_supply_voltage_v": dc_supply_voltage_v,
        "speed_rpm": speed_rpm,
        "magnet_temperature_c": magnet_temperature_c,
        "phase_advance_angle_deg": phase_advance_angle_deg,
        "frequency_hz": frequency_hz,
        "omega_elec": omega_elec,
        # Losses
        "total_losses_w": total_losses_w,
        "resistive_losses_w": resistive_losses_w,
        "iron_core_loss_w": iron_core_loss_w,
        "magnet_eddy_loss_w": magnet_eddy_loss_w,
        "rotor_structure_eddy_loss_w": rotor_structure_eddy_loss_w,
        "winding_eddy_loss_w": winding_eddy_loss_w,
        # Current
        "supply_current_a": rms_current_a,
        "peak_current_a": peak_current_a,
        "id_peak_a": id_peak_a,
        "iq_peak_a": iq_peak_a,
        # Resistance & Inductance
        "phase_resistance_ohm": phase_resistance_ohm,
        "ld_uh": ld_uh,
        "lq_uh": lq_uh,
        "ltt_uh": ltt_uh,
        # Flux & Back-EMF
        "pm_flux_linkage_mwb": pm_flux_linkage_mwb,
        "ke_v_per_rpm": ke_v_per_rpm,
        # Voltage breakdown (phase, peak)
        "v_resistive_phase_peak": v_resistive_phase_peak,
        "v_ld_peak": v_ld_peak,
        "v_lq_peak": v_lq_peak,
        "v_inductive_total_peak": v_inductive_total_peak,
        "v_backemf_phase_peak": v_backemf_phase_peak,
        "v_terminal_phase_peak": v_terminal_phase_peak,
        # Voltage breakdown (line-to-line, peak)
        "v_resistive_ll_peak": v_resistive_ll_peak,
        "v_inductive_ll_peak": v_inductive_ll_peak,
        "v_backemf_ll_peak": v_backemf_ll_peak,
        "v_terminal_ll_peak": v_terminal_ll_peak,
        # Performance constants
        "motor_constant_nm_per_sqrt_w": motor_constant_nm_per_sqrt_w,
        "motor_constant_nm_per_sqrt_w_resistance": motor_constant_nm_per_sqrt_w_resistance,
        "kt_nm_per_a": kt_nm_per_a,
        # Torque & Saturation
        "torque_nm": torque_nm,
        "torque_ripple_percent": torque_ripple_percent,
        "saturation_percent": saturation_percent,
        # Power factor
        "power_factor": power_factor,
        # Mechanical forces
        "airgap_axial_force_avg_n": airgap_axial_force_avg_n,
        "magnet_axial_force_pos_max_n": magnet_axial_force_pos_max_n,
        "magnet_axial_force_pos_min_n": magnet_axial_force_pos_min_n,
        "magnet_axial_force_neg_max_n": magnet_axial_force_neg_max_n,
        "magnet_axial_force_neg_min_n": magnet_axial_force_neg_min_n,
        "magnet_radial_force_pos_max_n": magnet_radial_force_pos_max_n,
        "magnet_radial_force_neg_max_n": magnet_radial_force_neg_max_n,
    }


def format_mass(mass_kg):
    """Format mass: use kg if >= 1kg, otherwise g."""
    mass_g = mass_kg * 1000
    if mass_g >= 1000:
        return f"{mass_kg:.2f}", "kg"
    return f"{mass_g:.1f}", "g"


def format_torque(torque_nm):
    """Format torque: use Nm if >= 1Nm, otherwise mNm."""
    torque_mnm = torque_nm * 1000
    if torque_mnm >= 1000:
        return f"{torque_nm:.2f}", "Nm"
    return f"{torque_mnm:.1f}", "mNm"


def format_motor_constant(km_nm_per_sqrt_w):
    """Format motor constant: use Nm/√W if >= 1, otherwise mNm/√W."""
    km_mnm = km_nm_per_sqrt_w * 1000
    if km_mnm >= 1000:
        return f"{km_nm_per_sqrt_w:.2f}", "Nm/√W"
    return f"{km_mnm:.1f}", "mNm/√W"


def format_torque_constant(kt_nm_per_a):
    """Format torque constant: use Nm/A if >= 1, otherwise mNm/A."""
    kt_mnm = kt_nm_per_a * 1000
    if kt_mnm >= 1000:
        return f"{kt_nm_per_a:.2f}", "Nm/A"
    return f"{kt_mnm:.1f}", "mNm/A"


def format_moment_of_inertia(inertia_g_cm2):
    """Format moment of inertia: use kg·m² if >= 10000 g·cm², otherwise g·cm²."""
    if inertia_g_cm2 >= 10000:
        inertia_kg_m2 = inertia_g_cm2 / 10000000
        return f"{inertia_kg_m2:.4f}", "kg·m²"
    return f"{inertia_g_cm2:.1f}", "g·cm²"


def create_phasor_diagram(values: dict) -> Drawing:
    """
    Create a PMSM phasor diagram in the d-q reference frame.
    
    The diagram shows:
    - d-axis (horizontal, pointing right) - aligned with PM flux
    - q-axis (vertical, pointing up) - 90° ahead of d-axis
    - Current phasor I with components Id and Iq
    - Back-EMF E (aligned with q-axis)
    - Voltage drops: V_R (in phase with I), V_Ld, V_Lq
    - Terminal voltage V (vector sum)
    """
    width = 500
    height = 350
    drawing = Drawing(width, height)
    
    # Center of the diagram (shifted left to make room for legend on right)
    cx, cy = width / 2 - 50, height / 2
    
    # Scale factor for voltage vectors (pixels per volt)
    max_voltage = max(
        values['v_terminal_phase_peak'],
        values['v_backemf_phase_peak'],
        1.0  # Avoid division by zero
    )
    scale = min(120, 120 / max_voltage * values['v_terminal_phase_peak'])
    scale = 100 / max_voltage if max_voltage > 0 else 1
    
    # Get values
    v_emf = values['v_backemf_phase_peak']
    v_r = values['v_resistive_phase_peak']
    v_ld = values['v_ld_peak']
    v_lq = values['v_lq_peak']
    id_a = values['id_peak_a']
    iq_a = values['iq_peak_a']
    i_peak = values['peak_current_a']
    
    # Current scale (for display purposes)
    i_scale = 50 / i_peak if i_peak > 0 else 1
    
    # Colors
    axis_color = colors.HexColor('#888888')
    emf_color = colors.HexColor('#1abb0e')  # Green - Back-EMF
    current_color = colors.HexColor('#0066cc')  # Blue - Current
    vr_color = colors.HexColor('#ff6600')  # Orange - Resistive drop
    vl_color = colors.HexColor('#9933ff')  # Purple - Inductive drop
    vt_color = colors.HexColor('#cc0000')  # Red - Terminal voltage
    
    # Draw axes
    axis_len = 140
    # d-axis (horizontal)
    drawing.add(Line(cx - axis_len, cy, cx + axis_len, cy,
                     strokeColor=axis_color, strokeWidth=1, strokeDashArray=[4, 2]))
    drawing.add(String(cx + axis_len + 5, cy - 4, 'd', fontSize=10,
                       fontName='SpaceGrotesk', fillColor=axis_color))
    # q-axis (vertical)
    drawing.add(Line(cx, cy - axis_len, cx, cy + axis_len,
                     strokeColor=axis_color, strokeWidth=1, strokeDashArray=[4, 2]))
    drawing.add(String(cx + 5, cy + axis_len - 10, 'q', fontSize=10,
                       fontName='SpaceGrotesk', fillColor=axis_color))
    
    def draw_arrow(x1, y1, x2, y2, color, label="", label_offset=(5, 5)):
        """Draw an arrow from (x1,y1) to (x2,y2) with arrowhead."""
        # Main line
        drawing.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=2))
        
        # Arrowhead
        angle = math.atan2(y2 - y1, x2 - x1)
        arrow_len = 8
        arrow_angle = math.pi / 6
        ax1 = x2 - arrow_len * math.cos(angle - arrow_angle)
        ay1 = y2 - arrow_len * math.sin(angle - arrow_angle)
        ax2 = x2 - arrow_len * math.cos(angle + arrow_angle)
        ay2 = y2 - arrow_len * math.sin(angle + arrow_angle)
        drawing.add(Polygon([x2, y2, ax1, ay1, ax2, ay2],
                            fillColor=color, strokeColor=color, strokeWidth=1))
        
        # Label
        if label:
            drawing.add(String(x2 + label_offset[0], y2 + label_offset[1], label,
                              fontSize=9, fontName='Helvetica', fillColor=color))
    
    # Back-EMF E (along q-axis, pointing up)
    e_len = v_emf * scale
    draw_arrow(cx, cy, cx, cy + e_len, emf_color, f"E={v_emf:.1f}V", (5, 0))
    
    # Current phasor I
    # Phase advance angle: positive angle means current leads the q-axis
    # In d-q frame: Id is along d-axis (negative for field weakening), Iq along q-axis
    i_d_len = id_a * i_scale  # Can be negative
    i_q_len = iq_a * i_scale
    i_end_x = cx + i_d_len
    i_end_y = cy + i_q_len
    draw_arrow(cx, cy, i_end_x, i_end_y, current_color,
               f"I={i_peak:.1f}A", (5, -10))
    
    # Voltage drops - build up from E to terminal voltage
    # In PMSM: V = E + I*R + jωLd*Id + jωLq*Iq
    # V_R is in phase with I
    # V_Ld = jωLd*Id (90° ahead of Id, so along q if Id is along d)
    # V_Lq = jωLq*Iq (90° ahead of Iq, so along -d if Iq is along q)
    
    # Starting point for voltage buildup (from E tip)
    vx, vy = cx, cy + e_len
    
    # V_R (in phase with current I)
    if i_peak > 0:
        vr_dx = v_r * scale * (id_a / i_peak) if i_peak > 0 else 0
        vr_dy = v_r * scale * (iq_a / i_peak) if i_peak > 0 else 0
    else:
        vr_dx, vr_dy = 0, 0
    vr_end_x = vx + vr_dx
    vr_end_y = vy + vr_dy
    if v_r > 0.01:
        draw_arrow(vx, vy, vr_end_x, vr_end_y, vr_color,
                   f"IR={v_r:.2f}V", (3, 3))
    vx, vy = vr_end_x, vr_end_y
    
    # V_Ld = jωLd*Id (90° ahead of d-axis current, so points in +q or -q)
    # If Id < 0 (field weakening), V_Ld points in -q direction
    vld_dx = 0
    vld_dy = v_ld * scale * (-1 if id_a < 0 else 1)
    vld_end_x = vx + vld_dx
    vld_end_y = vy + vld_dy
    if v_ld > 0.01:
        draw_arrow(vx, vy, vld_end_x, vld_end_y, vl_color,
                   f"ωLdId={v_ld:.2f}V", (3, 3))
    vx, vy = vld_end_x, vld_end_y
    
    # V_Lq = jωLq*Iq (90° ahead of q-axis current, so points in -d direction)
    vlq_dx = -v_lq * scale
    vlq_dy = 0
    vlq_end_x = vx + vlq_dx
    vlq_end_y = vy + vlq_dy
    if v_lq > 0.01:
        draw_arrow(vx, vy, vlq_end_x, vlq_end_y, vl_color,
                   f"ωLqIq={v_lq:.2f}V", (-55, 5))
    
    # Terminal voltage V (from origin to final point)
    draw_arrow(cx, cy, vlq_end_x, vlq_end_y, vt_color,
               f"V={values['v_terminal_phase_peak']:.1f}V", (5, -15))
    
    # Legend (on the right side)
    legend_x = width - 120
    legend_y = height - 40
    legend_items = [
        (emf_color, "E: Back-EMF"),
        (current_color, "I: Current"),
        (vr_color, "IR: Resistive drop"),
        (vl_color, "ωL: Inductive drops"),
        (vt_color, "V: Terminal voltage"),
    ]
    for i, (col, text) in enumerate(legend_items):
        drawing.add(Line(legend_x, legend_y - i * 14, legend_x + 15,
                        legend_y - i * 14, strokeColor=col, strokeWidth=2))
        drawing.add(String(legend_x + 20, legend_y - i * 14 - 3, text,
                          fontSize=8, fontName='Helvetica', fillColor=colors.black))
    
    return drawing


def generate_pdf(values: dict, output_path: str, motor_name: str = "",
                 is_confidential: bool = False,
                 source_folder: Path = None):
    """Generate a professional PDF datasheet from the extracted values."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=25*mm  # Extra space for footer
    )
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=28,
        spaceAfter=10,
        alignment=1,  # Center
        fontName='SpaceGrotesk-Bold',
        textColor=colors.HexColor('#222222')
    )
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=11,
        spaceAfter=25,
        alignment=1,
        fontName='SpaceGrotesk',
        textColor=colors.HexColor('#666666')
    )
    section_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=13,
        spaceBefore=18,
        spaceAfter=8,
        fontName='SpaceGrotesk-Bold',
        textColor=colors.HexColor('#222222'),
        borderColor=colors.HexColor('#1abb0e'),
        borderWidth=0,
        borderPadding=0
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
    
    # Operating point indicator
    op_type = "Peak" if values["is_peak"] else "Continuous"
    temp_c = values["magnet_temperature_c"]
    elements.append(Paragraph(f"Operating Point: {op_type} | Temperature: {temp_c:.0f} °C", subtitle_style))
    
    # Geometry Section
    elements.append(Paragraph("Geometry (active elements only)", section_style))
    
    # Format fill factors and coil dimensions (show "Not calculated" if null)
    ff = values['fill_factor']
    ff_str = f"{ff:.2f}" if ff is not None else "Not calculated"
    sff = values['slot_fill_factor']
    sff_str = f"{sff:.2f}" if sff is not None else "Not calculated"
    sw = values['slot_width_mm']
    sw_str = f"{sw:.3f}" if sw is not None else "Not calculated"
    acs = values['available_coil_space_mm']
    acs_str = f"{acs:.3f}" if acs is not None else "Not calculated"
    acw = values['assumed_coil_width_mm']
    acw_str = f"{acw:.3f}" if acw is not None else "Not calculated"
    ach = values['assumed_coil_height_mm']
    ach_str = f"{ach:.3f}" if ach is not None else "Not calculated"
    
    geom_data = [
        ["Parameter", "Value", "Unit"],
        ["Machine Outer Diameter", f"{values['machine_outer_diameter_mm']:.1f}", "mm"],
        ["Machine Inner Diameter", f"{values['machine_inner_diameter_mm']:.1f}", "mm"],
        ["Machine Thickness / Width", f"{values['machine_thickness_mm']:.1f}", "mm"],
        ["Stator Height", f"{values.get('stator_height_mm', 0):.1f}", "mm"],
        # ["Rotor Height", f"{values.get('rotor_height_mm', 0):.1f}", "mm"],
        ["Magnet Height", f"{values.get('magnet_height_mm', 0):.1f}", "mm"],
        ["Tooth Height", f"{values.get('teeth_thickness_mm', 0):.1f}", "mm"],
        ["Air Gap", f"{values['airgap_mm']:.2f}", "mm"],
        ["Fill Factor (input)", ff_str, "-"],
        ["Slot Fill Factor (calculated)", sff_str, "-"],
        ["Slot Width (tooth to tooth)", sw_str, "mm"],
        ["Available Coil Space", acs_str, "mm"],
        ["Assumed Coil Width (simulation)", acw_str, "mm"],
        ["Assumed Coil Height (simulation)", ach_str, "mm"],
    ]
    elements.append(create_table(geom_data))
    elements.append(Spacer(1, 10))
    
    # Mass Section
    elements.append(Paragraph("Mass Properties (active elements only)", section_style))
    machine_mass_val, machine_mass_unit = format_mass(values['machine_mass_kg'])
    rotor_mass_val, rotor_mass_unit = format_mass(values['rotor_mass_kg'])
    stator_mass_val, stator_mass_unit = format_mass(values['stator_mass_kg'])
    
    # Adding specifically requested masses
    cu_mass_val, cu_mass_unit = format_mass(values['copper_mass_kg'])
    st_steel_mass_val, st_steel_mass_unit = format_mass(values['stator_steel_mass_kg'])
    mag_mass_val, mag_mass_unit = format_mass(values['magnet_mass_kg'])

    rotor_structure_included = "Yes" if values['has_rotor_structure'] else "No"
    
    mass_data = [
        ["Parameter", "Value", "Unit"],
        ["Machine Mass", machine_mass_val, machine_mass_unit],
        ["Rotor Mass", rotor_mass_val, rotor_mass_unit],
        ["Stator Mass", stator_mass_val, stator_mass_unit],
        ["Total Copper Mass (pure copper)", cu_mass_val, cu_mass_unit],
        ["Total Stator Steel Mass", st_steel_mass_val, st_steel_mass_unit],
        ["Total Magnet Mass", mag_mass_val, mag_mass_unit],
        ["Rotor Structure Included", rotor_structure_included, "-"],
    ]
    # Add moment of inertia with rotor structure note if applicable
    inertia_label = "Rotor Moment of Inertia (active elements only)"
    if values['has_rotor_structure']:
        inertia_label += " - incl. simplified rotor structure"
    inertia_val, inertia_unit = format_moment_of_inertia(values['moment_of_inertia_g_cm2'])
    mass_data.append([inertia_label, inertia_val, inertia_unit])
    elements.append(create_table(mass_data))
    elements.append(Spacer(1, 10))
    
    # Page break before Electrical Section
    elements.append(PageBreak())
    
    # Electrical Section
    elements.append(Paragraph("Electrical Properties", section_style))
    elec_data = [
        ["Parameter", "Value", "Unit"],
        ["Supply Current (RMS)", f"{values['supply_current_a']:.3f}", "A"],
        ["Supply Current (Peak)", f"{values['peak_current_a']:.3f}", "A"],
        ["Id (Peak)", f"{values['id_peak_a']:.3f}", "A"],
        ["Iq (Peak)", f"{values['iq_peak_a']:.3f}", "A"],
        ["Phase Advance Angle", f"{values['phase_advance_angle_deg']:.1f}", "°elec"],
        ["Phase Resistance at operational temperature", f"{values['phase_resistance_ohm']*1000:.3f}", "mOhm"],
        ["D-Axis Inductance (Ld)", f"{values['ld_uh']:.3f}", "µH"],
        ["Q-Axis Inductance (Lq)", f"{values['lq_uh']:.3f}", "µH"],
        ["Terminal Inductance (Ltt = Ld + Lq)", f"{values['ltt_uh']:.3f}", "µH"],
        ["PM Flux Linkage", f"{values['pm_flux_linkage_mwb']:.3f}", "mWb"],
        ["Frequency at operating point (electrical)", f"{values['frequency_hz']:.3f}", "Hz"],
        ["Winding Configuration", "wye (star)", "-"],
        ["DC Supply Voltage", f"{values['dc_supply_voltage_v']:.3f}", "V"],
    ]
    # Add power factor if available
    if values.get('power_factor') is not None:
        elec_data.append(["Power Factor", f"{values['power_factor']:.3f}", "-"])
    elements.append(create_table(elec_data))
    elements.append(Spacer(1, 10))
    
    # Performance Section
    elements.append(Paragraph("Performance", section_style))
    torque_label = f"Torque ({'Peak' if values['is_peak'] else 'Continuous'})"
    torque_val, torque_unit = format_torque(values['torque_nm'])
    km_val, km_unit = format_motor_constant(values['motor_constant_nm_per_sqrt_w_resistance'])
    kt_val, kt_unit = format_torque_constant(values['kt_nm_per_a'])
    # Specific motor constant = Km / machine mass
    specific_km = values['motor_constant_nm_per_sqrt_w_resistance'] / values['machine_mass_kg']
    specific_km_val, specific_km_unit = format_motor_constant(specific_km)
    specific_km_unit = specific_km_unit + "/kg"
    perf_data = [
        ["Parameter", "Value", "Unit"],
        [torque_label, torque_val, torque_unit],
        ["Speed", f"{values['speed_rpm']:.1f}", "rpm"],
        ["Dimensionless motor constant", f"{values['motor_constant_nm_per_sqrt_w']*2/(values['machine_mass_kg'])**.5/values['machine_outer_diameter_mm']*1000:.1f}", "-"],
        ["BackEMF Constant (Ke, phase peak)", f"{values['ke_v_per_rpm']*1000:.1f}", "mV/rpm"],
        ["Motor Constant (Km, only resistive losses)", km_val, km_unit],
        ["Specific Motor Constant (Km / mass)", specific_km_val, specific_km_unit],
        ["Torque Constant (Kt, peak, no-load)", kt_val, kt_unit],
        ["Torque Ripple", f"{values['torque_ripple_percent']:.1f}", "%"],
        ["Saturation", f"{values['saturation_percent']:.1f}", "%"],
    ]
    elements.append(create_table(perf_data))
    elements.append(Spacer(1, 10))
    
    # Losses Section
    elements.append(Paragraph("Losses", section_style))
    loss_data = [
        ["Parameter", "Value", "Unit"],
        ["Total Losses", f"{values['total_losses_w']:.1f}", "W"],
        ["Resistive Losses", f"{values['resistive_losses_w']:.1f}", "W"],
        ["Iron Core Losses", f"{values['iron_core_loss_w']:.1f}", "W"],
        ["Magnet Eddy Current Losses", f"{values['magnet_eddy_loss_w']:.1f}", "W"],
        ["Rotor Structure Eddy Current Losses", f"{values['rotor_structure_eddy_loss_w']:.1f}", "W"],
        ["Winding Eddy Current Losses", f"{values['winding_eddy_loss_w']:.1f}", "W"],
    ]
    elements.append(create_table(loss_data))
    elements.append(Spacer(1, 10))
    
    # Configuration Section
    elements.append(Paragraph("Configuration", section_style))
    config_data = [
        ["Parameter", "Value", "Unit"],
        ["Number of Stators", f"{values['num_stators']}", "-"],
        ["Number of Rotors", f"{values['num_rotors']}", "-"],
        ["Number of Slots", f"{values['num_slots']}", "-"],
        ["Pole Pairs", f"{values['pole_pairs']}", "-"],
        ["Number of Parallel Paths", f"{values['parallel_paths']}", "-"],
        ["Number of Turns per Tooth (designed incl. parallel paths)", f"{values['turns_per_tooth_designed']}", "-"],
        ["Number of Phase Turns (all phases in series)", f"{values['phase_turns']}", "-"],
    ]
    elements.append(create_table(config_data))
    elements.append(Spacer(1, 10))
    
    # Page break before Winding Configuration Section
    elements.append(PageBreak())
    
    # Winding Configuration Section
    num_slots = values['num_slots']
    num_poles = values['pole_pairs'] * 2  # Convert pole pairs to poles
    winding_info, circular_drawing, linear_drawing = create_winding_layout_section(
        num_slots, num_poles
    )
    
    if winding_info is not None:
        elements.append(Paragraph("Winding Configuration", section_style))
        
        # Display schema text
        schema_text = winding_info['schema_display']
        balance_status = "Balanced" if winding_info['balanced'] else "Unbalanced"
        winding_type = "Distributed" if winding_info['distributed'] else "Concentrated"
        
        # Schema info paragraph with colored phases
        schema_colored = ""
        for ch in schema_text:
            if ch.lower() == 'a':
                schema_colored += f'<font color="#EA0000">{ch}</font>'
            elif ch.lower() == 'b':
                schema_colored += f'<font color="#008AE6">{ch}</font>'
            elif ch.lower() == 'c':
                schema_colored += f'<font color="#00CA00">{ch}</font>'
            else:
                schema_colored += ch
        
        schema_style = ParagraphStyle(
            'SchemaText',
            parent=styles['Normal'],
            fontSize=11,
            fontName='SpaceGrotesk-Bold',
            spaceAfter=5,
            alignment=1,  # Center
        )
        elements.append(Paragraph(f"Schema: {schema_colored}", schema_style))
        
        info_style = ParagraphStyle(
            'WindingInfo',
            parent=styles['Normal'],
            fontSize=9,
            fontName='SpaceGrotesk',
            spaceAfter=10,
            alignment=1,  # Center
            textColor=colors.HexColor('#666666'),
        )
        elements.append(Paragraph(
            f"{winding_type} Winding | {balance_status} | "
            f"Cogging: {winding_info['cogging_steps']}/rev | "
            f"Ripple: {winding_info['ripple_steps']}/rev",
            info_style
        ))
        
        # Add circular stator diagram (centered)
        if circular_drawing:
            # Wrap in a table to center it
            diagram_table = Table([[circular_drawing]], colWidths=[480])
            diagram_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            elements.append(diagram_table)
            elements.append(Spacer(1, 10))
    
    # Materials Section
    elements.append(Paragraph("Materials", section_style))
    materials_data = [
        ["Component", "Material", ""],
        ["Stator Core", values['stator_material'], "-"],
        ["Magnets", values['magnet_material'], "-"],
        ["Rotor Backiron", values['rotor_backiron_material'], "-"],
        ["Coil", values['coil_material'], "-"],
    ]
    elements.append(create_table(materials_data))
    elements.append(Spacer(1, 10))
    
    # Voltage Breakdown Section
    elements.append(Paragraph("Voltage Breakdown at Operating Point (with integer turns)", section_style))
    voltage_data = [
        ["Parameter", "Value", "Unit"],
        ["Back-EMF Voltage (Phase, Peak)", f"{values['v_backemf_phase_peak']:.3f}", "V"],
        ["Resistive Drop (Phase, Peak)", f"{values['v_resistive_phase_peak']:.3f}", "V"],
        ["Inductive Drop Ld (Peak)", f"{values['v_ld_peak']:.3f}", "V"],
        ["Inductive Drop Lq (Peak)", f"{values['v_lq_peak']:.3f}", "V"],
        ["Inductive Drop Total (Peak)", f"{values['v_inductive_total_peak']:.3f}", "V"],
        ["Terminal Voltage (Phase, Peak)", f"{values['v_terminal_phase_peak']:.3f}", "V"],
        ["", "", ""],
        ["Back-EMF Voltage (Line-to-Line, Peak)", f"{values['v_backemf_ll_peak']:.3f}", "V"],
        ["Resistive Drop (Line-to-Line, Peak)", f"{values['v_resistive_ll_peak']:.3f}", "V"],
        ["Inductive Drop (Line-to-Line, Peak)", f"{values['v_inductive_ll_peak']:.3f}", "V"],
        ["Terminal Voltage (Line-to-Line, Peak)", f"{values['v_terminal_ll_peak']:.3f}", "V"],
    ]
    elements.append(create_table(voltage_data))
    elements.append(Spacer(1, 10))
    
    # Phasor Diagram Section
    elements.append(Paragraph("Phasor Diagram Phase Values NOT Line-to-Line (d-q reference frame)", section_style))
    phasor_drawing = create_phasor_diagram(values)
    elements.append(phasor_drawing)
    elements.append(Spacer(1, 10))
    
    # Operating Curve Section (if image exists) - start on new page
    operating_curve_dir = Path(__file__).parent / "opearting_curve"
    operating_curve_path = operating_curve_dir / "image.png"
    if operating_curve_path.exists():
        elements.append(PageBreak())
        elements.append(Paragraph("Operating Curve", section_style))
        img_width = 140 * mm
        img_height = 100 * mm
        elements.append(Image(str(operating_curve_path), width=img_width, height=img_height))
        elements.append(Spacer(1, 5))
    
    # 3D Model Section (if STEP files are available) - comes last
    elements.append(PageBreak())

    model_image_path = str(IMAGES_DIR / "motor_3d_view.png")
    if render_step_files_to_image(model_image_path, width=800, height=600,
                                   step_files_dir=source_folder):
        elements.append(Paragraph("3D Model", section_style))
        # Scale image to fit, smaller to share page with operating curve
        img_width = 140 * mm
        img_height = 105 * mm  # Maintain aspect ratio (800:600 = 4:3)
        elements.append(Image(model_image_path, width=img_width, height=img_height))
    
    # Mechanical Properties Section
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Mechanical Properties", section_style))
    
    def fmt_force(val):
        """Format a force value, returning 'N/A' if None."""
        if val is None:
            return "N/A"
        return f"{val:.2f}"
    
    mech_data = [
        ["Parameter", "Value", "Unit"],
        ["Airgap Axial Force (Average)",
         fmt_force(values['airgap_axial_force_avg_n']), "N"],
        ["Magnet Axial Force Positive Maximum",
         fmt_force(values['magnet_axial_force_pos_max_n']), "N"],
        ["Magnet Axial Force Positive Minimum",
         fmt_force(values['magnet_axial_force_pos_min_n']), "N"],
        ["Magnet Axial Force Negative Maximum",
         fmt_force(values['magnet_axial_force_neg_max_n']), "N"],
        ["Magnet Axial Force Negative Minimum",
         fmt_force(values['magnet_axial_force_neg_min_n']), "N"],
    ]
    elements.append(create_table(mech_data))
    elements.append(Spacer(1, 10))
    
    # Glossary Section
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Glossary", section_style))
    glossary_style = ParagraphStyle(
        'Glossary',
        parent=getSampleStyleSheet()['Normal'],
        fontName='SpaceGrotesk',
        fontSize=9,
        textColor=colors.HexColor('#333333'),
        leading=14,
    )
    glossary_items = [
        "<b>Peak</b> — Refers to 0-to-peak amplitude (NOT peak-to-peak). "
        "For sinusoidal waveforms: Peak = RMS × <font name='Helvetica'>√</font>2.",
        "<b>RMS</b> — Root Mean Square, the equivalent DC value for power calculations.",
        "<b>Line-to-Line (L-L)</b> — Voltage measured between two phases. "
        "For wye connection: V_LL = V_phase × <font name='Helvetica'>√</font>3.",
    ]
    for item in glossary_items:
        elements.append(Paragraph(f"• {item}", glossary_style))
        elements.append(Spacer(1, 4))
    
    footer_func = create_page_footer(is_confidential)
    doc.build(elements, onFirstPage=footer_func, onLaterPages=footer_func)


def create_table(data: list) -> Table:
    """Create a styled table from data."""
    table = Table(data, colWidths=[120*mm, 40*mm, 30*mm])
    table.setStyle(TableStyle([
        # Header row - clean minimal style
        ('BACKGROUND', (0, 0), (-1, 0), colors.white),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#222222')),
        ('FONTNAME', (0, 0), (1, 0), 'SpaceGrotesk-Bold'),
        ('FONTNAME', (2, 0), (2, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
        ('ALIGN', (1, 0), (-1, 0), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#1abb0e')),
        
        # Data rows - columns 0 and 1
        ('FONTNAME', (0, 1), (1, -1), 'SpaceGrotesk'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#333333')),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 7),
        ('TOPPADDING', (0, 1), (-1, -1), 7),
        
        # Unit column (column 2) - use Helvetica for proper symbol support
        ('FONTNAME', (2, 1), (2, -1), 'Helvetica'),
        
        # Subtle row separators
        ('LINEBELOW', (0, 1), (-1, -2), 0.5, colors.HexColor('#e0e0e0')),
        ('LINEBELOW', (0, -1), (-1, -1), 1, colors.HexColor('#e0e0e0')),
    ]))
    return table


def main():
    """Main CLI entry point."""
    print("=" * 60)
    print("  WheemX Simulation Output to PDF Datasheet Converter")
    print("=" * 60)
    print()
    
    # Get input folder
    if len(sys.argv) > 1:
        input_arg = sys.argv[1]
    else:
        input_arg = input("Enter the path to the source folder: ").strip()
        if input_arg.startswith('"') and input_arg.endswith('"'):
            input_arg = input_arg[1:-1]

    input_path = Path(input_arg)
    if not input_path.exists():
        print(f"Error: Path not found: {input_arg}")
        sys.exit(1)

    # Resolve source folder and JSON file
    if input_path.is_dir():
        source_folder = input_path
        json_candidates = sorted(source_folder.glob("*output.json"))
        if not json_candidates:
            print(f"Error: No *output.json file found in {source_folder}")
            sys.exit(1)
        json_path = json_candidates[-1]  # use most recent if multiple
        motor_name = source_folder.name
    else:
        # Fallback: direct JSON file path (legacy behaviour)
        json_path = input_path
        source_folder = None
        motor_name = input_path.stem

    # Load JSON
    print(f"\nLoading: {json_path.name}")
    try:
        data = load_json(str(json_path))
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON file: {e}")
        sys.exit(1)
    
    # Calculate turns
    turns = calculate_turns(data)
    if 0:
        print("\n########################")
        print("\nCAUTION HARD CODED TURNS")
        print("\n########################")
        turns = 20
    dc_voltage = data["Simulation"]["DCSupplyVoltage"]
    peak_voltage = data["Simulation"]["Output"]["PeakLineToLineTerminalVoltage_SVM_V"]
    
    print(f"\n  DC Supply Voltage: {dc_voltage} V")
    print(f"  Peak Line-to-Line Terminal Voltage (SVM): {peak_voltage:.4f} V")
    print(f"  Calculated Number of Turns per Tooth: {turns}")
    
    # Ask for operating point type
    print("\n" + "-" * 40)
    while True:
        response = input("Is the selected operating point PEAK or CONTINUOUS? (p/c): ").strip().lower()
        if response in ['p', 'peak']:
            is_peak = True
            break
        elif response in ['c', 'continuous', 'cont']:
            is_peak = False
            break
        else:
            print("Please enter 'p' for peak or 'c' for continuous.")

    # Ask for safety factor
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
    
    # Extract and convert values
    print(f"\nProcessing data for {'Peak' if is_peak else 'Continuous'} operating point...")
    values = extract_and_convert_values(data, turns, is_peak, safety_factor, parallel_paths)
    
    # Ask for optional torque override
    original_torque = values['torque_nm']
    response = input(f"Do you want to use a different torque? (current: {original_torque:.4f} Nm, press Enter to keep): ").strip()
    if response:
        try:
            new_torque = float(response)
            if new_torque != original_torque:
                # Calculate scaling factor
                k = new_torque / original_torque
                # Scale dependent values
                values['torque_nm'] = new_torque
                values['supply_current_a'] = values['supply_current_a'] * k
                # Keep the ratio between resistive and total losses the same
                original_resistive = values['resistive_losses_w']
                original_total = values['total_losses_w']
                resistive_ratio = original_resistive / original_total
                # Resistive losses scale with k^2
                new_resistive = original_resistive * (k ** 2)
                # Total losses scaled to maintain the same ratio
                new_total = new_resistive / resistive_ratio
                values['resistive_losses_w'] = new_resistive
                values['total_losses_w'] = new_total
                print(f"  Scaled torque: {original_torque:.4f} -> {new_torque:.4f} Nm (factor: {k:.3f})")
        except ValueError:
            print("Invalid value, keeping original torque.")
    
    # Ask if confidential
    conf_response = input("Mark as confidential? (y/n, default n): ").strip().lower()
    is_confidential = conf_response in ['y', 'yes']
    
    # Generate output filename (use folder name / stem as motor name)
    op_suffix = "peak" if is_peak else "continuous"
    output_filename = motor_name + f"_datasheet_{op_suffix}.pdf"
    output_path = input_path.parent / output_filename

    # Generate PDF
    print(f"Generating PDF: {output_filename}")
    generate_pdf(values, str(output_path), motor_name, is_confidential,
                 source_folder=source_folder)
    
    print(f"\n✓ Datasheet saved to: {output_path}")
    print()


if __name__ == "__main__":
    main()