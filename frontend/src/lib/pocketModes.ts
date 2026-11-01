/**
 * Binding Pocket and Interactions modes for the DockShift 3Dmol viewer.
 *
 * Everything here is derived from the coordinates actually loaded from
 * PDB 9Q14. Nothing is invented:
 *
 *  - The pocket is selected by DISTANCE FROM THE LIGAND, not by chain id.
 *    That matters: the chain assignment in this project is unverified, and
 *    proximity selection does not depend on it being right.
 *  - Contacts are HEAVY-ATOM DISTANCES measured between real atoms. They
 *    are not bonds. 9Q14 is a 3.00 A cryo-EM structure, so hydrogens are
 *    not resolved and a hydrogen bond cannot be confirmed from it — only a
 *    donor/acceptor separation consistent with one. The UI must say so.
 *  - If the ligand is not present in the loaded model, these functions
 *    report that and render nothing rather than drawing a placeholder.
 */

/** BIBR1532 as deposited in 9Q14. Verified against RCSB: component 55C. */
export const LIGAND_RESN = '55C';
export const LIGAND_SEL = { resn: LIGAND_RESN } as const;

export const POCKET_SURFACE_RADIUS = 9.0;   // A, surface extent around ligand
export const POCKET_RESIDUE_RADIUS = 5.0;   // A, residues drawn as sticks
/** Heavy-atom separation consistent with an H-bond (Jeffrey). Not proof. */
export const POLAR_CUTOFF = 3.6;
/** Carbon-carbon separation counted as van der Waals proximity. */
export const VDW_CUTOFF = 4.2;

export const TURQUOISE = '#3FD5C0';
export const POLAR_COLOR = '#FFD166';
export const VDW_COLOR = '#8AA0B4';

export type ContactKind = 'polar' | 'vdw';

export interface Contact {
  kind: ContactKind;
  distance: number;
  ligandAtom: string;
  proteinAtom: string;
  residue: string;
  chain: string;
  resi: number;
  start: { x: number; y: number; z: number };
  end: { x: number; y: number; z: number };
}

export interface LigandProbe {
  found: boolean;
  atomCount: number;
  chains: string[];
  resi: number[];
  elements: string[];
  centroid: { x: number; y: number; z: number } | null;
}

/** Handles for artifacts a mode added, so the next mode can clear them. */
export interface ModeArtifacts {
  surfaces: any[];
  shapes: boolean;
  labels: boolean;
}

export const emptyArtifacts = (): ModeArtifacts => ({
  surfaces: [], shapes: false, labels: false,
});

const EL = (a: any): string =>
  String(a?.elem ?? a?.element ?? '').trim().toUpperCase();

const isPolarHeavy = (a: any) => ['N', 'O'].includes(EL(a));
const isCarbon = (a: any) => EL(a) === 'C';

const dist = (a: any, b: any) =>
  Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2);

/**
 * Confirm the ligand is really in the loaded structure, and describe it.
 * Call this before rendering either mode — if `found` is false, show the
 * user an honest message instead of an empty pocket.
 */
export function probeLigand(viewer: any): LigandProbe {
  const empty: LigandProbe = {
    found: false, atomCount: 0, chains: [], resi: [], elements: [], centroid: null,
  };
  try {
    const model = viewer?.getModel?.();
    if (!model) return empty;
    const atoms = model.selectedAtoms(LIGAND_SEL) ?? [];
    if (!atoms.length) return empty;
    const chains = Array.from(new Set(atoms.map((a: any) => String(a.chain))));
    const resi = Array.from(new Set(atoms.map((a: any) => Number(a.resi))));
    const elements = Array.from(new Set(atoms.map(EL))).filter(Boolean);
    const c = atoms.reduce(
      (acc: any, a: any) => ({ x: acc.x + a.x, y: acc.y + a.y, z: acc.z + a.z }),
      { x: 0, y: 0, z: 0 }
    );
    return {
      found: true,
      atomCount: atoms.length,
      chains: chains as string[],
      resi: (resi as number[]).sort((p, q) => p - q),
      elements: elements as string[],
      centroid: { x: c.x / atoms.length, y: c.y / atoms.length, z: c.z / atoms.length },
    };
  } catch {
    return empty;
  }
}

/** Remove surfaces/shapes/labels a previous mode added. Styles are not touched. */
export function clearArtifacts(viewer: any, art: ModeArtifacts): ModeArtifacts {
  if (!viewer) return emptyArtifacts();
  for (const s of art.surfaces) {
    try { viewer.removeSurface(s); } catch { /* already gone */ }
  }
  if (art.shapes) { try { viewer.removeAllShapes(); } catch { /* noop */ } }
  if (art.labels) { try { viewer.removeAllLabels(); } catch { /* noop */ } }
  return emptyArtifacts();
}

/** Protein atoms lining the ligand, selected by distance — chain-agnostic. */
const pocketSel = (radius: number) => ({
  within: { distance: radius, sel: LIGAND_SEL },
  not: LIGAND_SEL,
  hetflag: false,
  byres: true,
});

/** Ball-and-stick with element colours (Jmol scheme). */
const ligandStyle = () => ({
  stick: { radius: 0.17, colorscheme: 'Jmol' },
  sphere: { scale: 0.26, colorscheme: 'Jmol' },
});

export interface PocketResult {
  ok: boolean;
  reason?: string;
  probe: LigandProbe;
  artifacts: ModeArtifacts;
  pocketAtomCount: number;
}

/**
 * Binding Pocket mode: turquoise translucent surface over the real pocket,
 * BIBR1532 in ball-and-stick, everything distant hidden.
 */
export function renderBindingPocket(
  viewer: any,
  $3Dmol: any,
  previous: ModeArtifacts,
  opts: { focusCamera?: boolean } = {}
): PocketResult {
  const artifacts = clearArtifacts(viewer, previous);
  const probe = probeLigand(viewer);
  if (!probe.found) {
    return {
      ok: false,
      reason: `Ligand ${LIGAND_RESN} is not present in the loaded model.`,
      probe, artifacts, pocketAtomCount: 0,
    };
  }

  // Hide everything, then reveal only the pocket and the ligand.
  viewer.setStyle({}, {});

  const sel = pocketSel(POCKET_SURFACE_RADIUS);
  let pocketAtomCount = 0;
  try {
    pocketAtomCount = (viewer.getModel()?.selectedAtoms(sel) ?? []).length;
  } catch { /* count is cosmetic */ }

  // Faint cartoon under the surface gives the pocket a readable shape.
  viewer.setStyle(sel, { cartoon: { color: TURQUOISE, opacity: 0.45, thickness: 0.3 } });

  try {
    const surface = viewer.addSurface(
      $3Dmol.SurfaceType.VDW,
      { opacity: 0.72, color: TURQUOISE },
      sel
    );
    artifacts.surfaces.push(surface);
  } catch (err) {
    // A surface failure must not take the mode down with it.
    console.warn('[DockShift] pocket surface could not be generated:', err);
  }

  viewer.setStyle(LIGAND_SEL, ligandStyle());

  if (opts.focusCamera !== false) {
    viewer.zoomTo(LIGAND_SEL);
    viewer.zoom(0.75);
  }
  viewer.render();
  return { ok: true, probe, artifacts, pocketAtomCount };
}

export interface InteractionsResult extends PocketResult {
  contacts: Contact[];
}

/**
 * Interactions mode: fade the surface, show lining residues as sticks, and
 * draw measured heavy-atom contacts. The camera is left exactly as it was
 * unless the caller asks otherwise.
 */
export function renderInteractions(
  viewer: any,
  $3Dmol: any,
  previous: ModeArtifacts,
  opts: { showLabels?: boolean; maxContacts?: number } = {}
): InteractionsResult {
  const artifacts = clearArtifacts(viewer, previous);
  const probe = probeLigand(viewer);
  if (!probe.found) {
    return {
      ok: false,
      reason: `Ligand ${LIGAND_RESN} is not present in the loaded model.`,
      probe, artifacts, pocketAtomCount: 0, contacts: [],
    };
  }

  viewer.setStyle({}, {});

  const nearSel = pocketSel(POCKET_RESIDUE_RADIUS);
  const wideSel = pocketSel(POCKET_SURFACE_RADIUS);

  // Context: a very faint surface so the pocket does not disappear entirely.
  try {
    const ghost = viewer.addSurface(
      $3Dmol.SurfaceType.VDW, { opacity: 0.12, color: TURQUOISE }, wideSel
    );
    artifacts.surfaces.push(ghost);
  } catch { /* optional */ }

  viewer.setStyle(nearSel, {
    stick: { radius: 0.13, colorscheme: 'Jmol' },
  });
  viewer.setStyle(LIGAND_SEL, ligandStyle());

  const contacts = measureContacts(viewer, opts.maxContacts ?? 12);

  for (const c of contacts) {
    try {
      viewer.addCylinder({
        start: c.start,
        end: c.end,
        radius: c.kind === 'polar' ? 0.045 : 0.03,
        dashed: true,
        fromCap: 1,
        toCap: 1,
        color: c.kind === 'polar' ? POLAR_COLOR : VDW_COLOR,
      });
      artifacts.shapes = true;
      if (opts.showLabels) {
        viewer.addLabel(`${c.distance.toFixed(2)} Å`, {
          position: {
            x: (c.start.x + c.end.x) / 2,
            y: (c.start.y + c.end.y) / 2,
            z: (c.start.z + c.end.z) / 2,
          },
          backgroundColor: '#0E1718',
          backgroundOpacity: 0.75,
          fontColor: c.kind === 'polar' ? POLAR_COLOR : '#D7E3EC',
          fontSize: 11,
          borderThickness: 0,
          inFront: true,
        });
        artifacts.labels = true;
      }
    } catch (err) {
      console.warn('[DockShift] contact render notice:', err);
    }
  }

  viewer.render();
  return { ok: true, probe, artifacts, pocketAtomCount: 0, contacts };
}

/**
 * Measure heavy-atom separations between the ligand and the protein.
 *
 * These are MEASUREMENTS, not bond assignments. A `polar` result means two
 * N/O atoms sit at a separation consistent with a hydrogen bond; because
 * 9Q14 resolves no hydrogens, whether one exists cannot be decided here.
 * One contact is kept per residue — the shortest — so the view stays legible.
 */
export function measureContacts(viewer: any, maxContacts = 12): Contact[] {
  const model = viewer?.getModel?.();
  if (!model) return [];

  let ligandAtoms: any[] = [];
  let nearAtoms: any[] = [];
  try {
    ligandAtoms = model.selectedAtoms(LIGAND_SEL) ?? [];
    nearAtoms = model.selectedAtoms({
      within: { distance: VDW_CUTOFF, sel: LIGAND_SEL },
      not: LIGAND_SEL,
      hetflag: false,
    }) ?? [];
  } catch {
    return [];
  }
  if (!ligandAtoms.length || !nearAtoms.length) return [];

  const best = new Map<string, Contact>();

  for (const p of nearAtoms) {
    if (!EL(p)) continue;
    for (const l of ligandAtoms) {
      const d = dist(l, p);
      let kind: ContactKind | null = null;
      if (isPolarHeavy(l) && isPolarHeavy(p) && d <= POLAR_CUTOFF) {
        kind = 'polar';
      } else if (isCarbon(l) && isCarbon(p) && d <= VDW_CUTOFF) {
        kind = 'vdw';
      }
      if (!kind) continue;

      const key = `${p.chain}:${p.resi}`;
      const existing = best.get(key);
      // Prefer a polar contact; otherwise the shorter one.
      const better =
        !existing ||
        (kind === 'polar' && existing.kind === 'vdw') ||
        (kind === existing.kind && d < existing.distance);
      if (!better) continue;

      best.set(key, {
        kind,
        distance: d,
        ligandAtom: String(l.atom ?? EL(l)),
        proteinAtom: String(p.atom ?? EL(p)),
        residue: String(p.resn ?? 'UNK'),
        chain: String(p.chain ?? '?'),
        resi: Number(p.resi ?? 0),
        start: { x: l.x, y: l.y, z: l.z },
        end: { x: p.x, y: p.y, z: p.z },
      });
    }
  }

  return Array.from(best.values())
    .sort((a, b) => (a.kind === b.kind ? a.distance - b.distance : a.kind === 'polar' ? -1 : 1))
    .slice(0, maxContacts);
}

/** Make the ligand clickable so a player can select it in the viewer. */
export function makeLigandSelectable(
  viewer: any,
  onPick: (probe: LigandProbe) => void
): void {
  try {
    viewer.setClickable(LIGAND_SEL, true, () => onPick(probeLigand(viewer)));
  } catch (err) {
    console.warn('[DockShift] could not make ligand clickable:', err);
  }
}

/** Brief highlight pulse once the player finds the inhibitor. */
export function pulseLigand(viewer: any, onDone?: () => void): void {
  let step = 0;
  const frames = [0.52, 0.40, 0.34, 0.26];
  const tick = () => {
    if (!viewer) return;
    try {
      viewer.setStyle(LIGAND_SEL, {
        stick: { radius: 0.17, colorscheme: 'Jmol' },
        sphere: { scale: frames[step], colorscheme: 'Jmol' },
      });
      viewer.render();
    } catch { /* viewer may be gone */ }
    step += 1;
    if (step < frames.length) {
      setTimeout(tick, 110);
    } else {
      try {
        viewer.setStyle(LIGAND_SEL, ligandStyle());
        viewer.render();
      } catch { /* noop */ }
      onDone?.();
    }
  };
  tick();
}
