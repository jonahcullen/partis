#!/usr/bin/env python
import sys
import colored_traceback.always
import os
import yaml
import argparse

sys.path.insert(1, './python')
import utils
import treeutils

parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('action', choices=['train', 'test'])
parser.add_argument('--label', default='test-dtr-v0')
args = parser.parse_args()

vsets = {
    'all' : {
        'within-families' : ['lbi', 'cons-dist', 'edge-dist', 'lbr', 'shm'],
        'among-families' : ['lbi', 'cons-dist', 'edge-dist', 'lbr', 'shm', 'fay-wu-h', 'cons-seq-shm', 'mean-shm', 'max-lbi', 'max-lbr']},
    'med' : {
        'within-families' : ['lbi', 'cons-dist', 'shm'],
        'among-families' : ['lbi', 'cons-dist', 'shm', 'fay-wu-h', 'max-lbi', 'max-lbr']},
    'min' : {
        'within-families' : ['lbi', 'cons-dist'],
        'among-families' : ['lbi', 'cons-dist', 'mean-shm', 'max-lbi']}
}

baseworkdir = '%s/_tmp' % os.getcwd()

basecmds = {
    'test-dtr-v0' : './test/cf-tree-metrics.py --label test-dtr-v0 --n-replicates 2 --n-sim-events-per-proc 5 --carry-cap-list 750 --obs-times-list 75 --n-sim-seqs-per-gen-list 80 --lb-tau-list 0.0025',
    'choose-among-families-v3' : './test/cf-tree-metrics.py --label choose-among-families-v3 --n-replicates 10 --n-sim-events-per-proc 30 --slurm --carry-cap-list 1500 --obs-times-list 150 --n-sim-seqs-per-gen-list 150 --lb-tau-list 0.0025 --dont-observe-common-ancestors',
    'dtr-train-v0' : './test/cf-tree-metrics.py --label dtr-train-v0 --n-replicates 5 --n-sim-events-per-proc 1000 --slurm --carry-cap-list 1500 --obs-times-list 150 --n-sim-seqs-per-gen-list 150 --selection-strength 0.75 --lb-tau-list 0.0025 --parameter-variances carry-cap,2000:obs-times,150:n-sim-seqs-per-generation,200:selection-strength,0.5',
}
basecmd = basecmds[args.label]

basecmd += ' --actions get-tree-metrics --metric-method dtr'
basepath = '/fh/fast/matsen_e/dralph/partis/tree-metrics/%s' % args.label
training_seed = 0  # just for output file names, I don't really want to keep track of here, but utils.run_cmds() requires it

cmdfos = []
for ensemble in ['grad-boost', 'ada-boost', 'forest']: #, 'bag']:
    for n_estimators in [10, 30, 100]:
        for vsname, varset in vsets.items():
            cmd = basecmd
            paramstr = 'ensemble_%s_n-estimators_%d_vars_%s' % (ensemble, n_estimators, vsname)
            xtrastrs = {s : '%s_%s' % (s, paramstr) for s in ['train', 'test']}
            modeldir = '%s/seed-%d/dtr/%s-dtr-models' % (basepath, training_seed, xtrastrs['train'])
            workdir = '%s/%s' % (baseworkdir, paramstr)
            cfgfname = '%s/cfg.yaml' % workdir
            cmd += ' --dtr-cfg %s' % cfgfname
            if args.action == 'train':
                if not os.path.exists(workdir):
                    os.makedirs(workdir)
                with open(cfgfname, 'w') as cfile:
                    yaml.dump({'ensemble' : ensemble, 'n_estimators' : n_estimators, 'vars' : varset}, cfile, width=200)
                cmd += ' --iseed %d --extra-plotstr %s' % (training_seed, xtrastrs['train'])
                modelfnames = [treeutils.dtrfname(modeldir, cg) for cg in treeutils.cgroups]
                outfname = modelfnames[0]
                logdir = os.path.dirname(outfname)
            elif args.action == 'test':
                cmd += ' --dtr-path %s --extra-plotstr %s' % (modeldir, xtrastrs['test'])
                TMP_SEED = 0
                outfname = ['%s/seed-%d/dtr/%s-plots/true-tree-metrics/%s-dtr/%s-dtr-vs-affinity-ptiles/%s-dtr-vs-affinity-true-tree-ptiles-all-clusters.yaml' % (basepath, TMP_SEED, xtrastrs['test'], cg, cg, cg) for cg in treeutils.cgroups][0]
                logdir = '%s/seed-%d/dtr/%s-plots' % (basepath, TMP_SEED, xtrastrs['test'])
            else:
                assert False

            print '    %s' % logdir

            # utils.simplerun(cmd, debug=True) #, dryrun=True)
            cmdfo = {'cmd_str' : cmd,
                     'outfname' : outfname,
                     'logdir' : logdir,
                     'workdir' : workdir,
            }  # I don't think I actually use the work dir
            cmdfos.append(cmdfo)

print '  starting %d jobs' % len(cmdfos)
utils.run_cmds(cmdfos, n_max_procs=utils.auto_n_procs(), proc_limit_str='test/cf-tree-metrics', debug='print')
