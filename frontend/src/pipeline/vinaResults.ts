/**
 * AutoDock Vina results from the analogue enumeration run.
 *
 * These ARE real computed output, unlike the pose/trajectory reference sets:
 * run 'run-d1018d021e07', twelve analogues enumerated from BIBR1532 and docked against the
 * rigid receptor, all twelve succeeding.
 *
 * The run validates itself first. The co-crystal ligand was redocked and
 * reproduced its experimental pose to 0.75 A, inside the 2.0 A gate the project
 * set before any candidate score counts, and scored -10.441 kcal/mol. Every delta
 * below is measured against that reference.
 *
 * The honest headline is that enumeration mostly did not help: one analogue of
 * twelve beats the parent, and by 0.23 kcal/mol, which is inside the noise of
 * the scoring function.
 */

export const VINA_RUN_ID = 'run-d1018d021e07';
export const VINA_GENERATOR = 'local deterministic R-group enumeration (not a trained model)';
export const VINA_SEED = 20261031;

export const VINA_REFERENCE = {
  compound: 'BIBR1532_55C',
  score: -10.441,
  redockRmsd: 0.75,
};

/** Scope limit stated by the run itself; shown wherever these scores appear. */
export const VINA_SCOPE_WARNING = 'Scores rank molecules under one scoring function against one rigid receptor. They are not measured affinities and not evidence of anticancer activity. No candidate here has experimental data of any kind.';

export interface VinaAnalogue {
  id: string;
  smiles: string;
  /** Best Vina score, kcal/mol. More negative ranks better. */
  vina: number;
  /** Difference against the redocked reference; negative beats the parent. */
  delta: number;
}

/** Ranked best first. */
export const VINA_ANALOGUES: VinaAnalogue[] = [
  { id: 'g010', smiles: 'C/C(=C\\C(=O)Nc1ccccc1C(=O)O)c1cc(Cl)c2ccccc2c1', vina: -10.669, delta: -0.228 },
  { id: 'g004', smiles: 'C/C(=C\\C(=O)Nc1ccccc1C(=O)O)c1cc(C(C)C)c2ccccc2c1', vina: -10.398, delta: 0.043 },
  { id: 'g000', smiles: 'C/C(=C\\C(=O)Nc1ccccc1C(=O)O)c1ccc2cc(F)ccc2c1', vina: -10.24, delta: 0.201 },
  { id: 'g002', smiles: 'CCc1cc2ccccc2cc1/C(C)=C/C(=O)Nc1ccccc1C(=O)O', vina: -10.038, delta: 0.403 },
  { id: 'g001', smiles: 'C/C(=C\\C(=O)Nc1ccccc1C(=O)O)c1ccc2ccc(C#N)cc2c1', vina: -9.598, delta: 0.843 },
  { id: 'g007', smiles: 'C/C(=C\\C(=O)Nc1ccccc1C(=O)O)c1ccc2c(C#N)cccc2c1', vina: -9.514, delta: 0.927 },
  { id: 'g003', smiles: 'C/C(=C\\C(=O)Nc1ccccc1C(=O)O)c1ccc2cccc(C(C)C)c2c1', vina: -8.539, delta: 1.902 },
  { id: 'g011', smiles: 'C/C(=C\\C(=O)Nc1ccccc1C(=O)O)c1ccc2ccc(C(C)C)cc2c1', vina: -8.481, delta: 1.96 },
  { id: 'g008', smiles: 'C/C(=C\\C(=O)Nc1ccccc1C(=O)O)c1ccc2ccccc2c1C', vina: -8.449, delta: 1.992 },
  { id: 'g005', smiles: 'CCc1ccc2cc(/C(C)=C/C(=O)Nc3ccccc3C(=O)O)ccc2c1', vina: -7.801, delta: 2.64 },
  { id: 'g006', smiles: 'C/C(=C\\C(=O)Nc1ccccc1C(=O)O)c1ccc2ccccc2c1C(N)=O', vina: -7.587, delta: 2.854 },
  { id: 'g009', smiles: 'C/C(=C\\C(=O)Nc1ccccc1C(=O)O)c1ccc2ccccc2c1C(C)C', vina: -7.449, delta: 2.992 },
];

export const vinaBest = () => VINA_ANALOGUES[0];
export const vinaBeatingParent = () => VINA_ANALOGUES.filter((a) => a.delta < 0);
