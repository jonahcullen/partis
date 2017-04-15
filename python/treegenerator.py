#!/usr/bin/env python
""" Read the inferred tree parameters from Connor's json files, and generate a bunch of trees to later sample from. """

import sys
import os
import re
import random
import json
import numpy
import math
from cStringIO import StringIO
import tempfile
from subprocess import check_call
import baltic

from hist import Hist
import utils

# ----------------------------------------------------------------------------------------
def print_ascii_tree(treestr):
    if 'Bio.Phylo' not in sys.modules:
        from Bio import Phylo
    if len(re.findall('t', treestr)) > 1:  # if more than one leaf
        sys.modules['Bio.Phylo'].draw_ascii(sys.modules['Bio.Phylo'].read(StringIO(treestr), 'newick'), column_width=80)
    else:
        print '    one leaf'

# ----------------------------------------------------------------------------------------
class TinyLeaf(object):
    def __init__(self, name, length, height):
        self.name = name
        self.numName = self.name
        self.length = length
        self.height = height
        self.branchType = 'leaf'

# ----------------------------------------------------------------------------------------
class OneLeafTree(object):
    def __init__(self, name, height):
        self.leaves = [TinyLeaf(name, height, height)]
        self.Objects = self.leaves
    def traverse_tree(self):
        self.leaves[0].height = self.leaves[0].length
    def toString(self, numName=None):
        return '%s:%.15f;' % (self.leaves[0].name, self.leaves[0].length)

# ----------------------------------------------------------------------------------------
def get_btree(treestr):
    if treestr.count(':') == 1:  # one-leaf tree
        name, lengthstr = treestr.strip().rstrip(';').split(':')
        tree = OneLeafTree(name, float(lengthstr))
    else:
        tree = baltic.tree()
        baltic.make_tree(treestr, tree, verbose=False)
    tree.traverse_tree()
    return tree

# ----------------------------------------------------------------------------------------
def get_leaf_node_depths(treestr):
    tree = get_btree(treestr)
    return {l.numName : l.height for l in tree.leaves}

# ----------------------------------------------------------------------------------------
def get_mean_height(treestr):
    tree = get_btree(treestr)
    heights = [l.height for l in tree.leaves]
    mean_height = sum(heights) / len(heights)
    return mean_height

# ----------------------------------------------------------------------------------------
def rescale_tree(treestr, new_height, debug=False):
    """ 
    Rescale the branch lengths in <treestr> (newick-formatted) by <factor>
    I.e. multiply each float in <treestr> by <factor>.
    """

    tree = get_btree(treestr)
    mean_height = get_mean_height(treestr)
    for ln in tree.Objects:
        old_length = ln.length
        ln.length *= new_height / mean_height  # everybody's heights should be the same... but they never quite were when I was using Bio.Phylo, so, uh. yeah, uh. not sure what to do
        if debug:
            print '  %5s  %7e  -->  %7e' % (ln.numName if ln.branchType == 'leaf' else ln.branchType, old_length, ln.length)
    tree.traverse_tree()
    treestr = tree.toString(numName=True)
    for leaf in get_btree(treestr).leaves:
        if not utils.is_normed(leaf.height / new_height, this_eps=1e-8):
            raise Exception('tree not rescaled properly:   %.10f   %.10f    %e' % (leaf.height, new_height, (leaf.height - new_height) / new_height))
    return treestr

# ----------------------------------------------------------------------------------------
class TreeGenerator(object):
    def __init__(self, args, parameter_dir, seed):
        self.args = args
        self.branch_lengths = self.read_mute_freqs(parameter_dir)  # for each region (and 'all'), a list of branch lengths and a list of corresponding probabilities (i.e. two lists: bin centers and bin contents). Also, the mean of the hist.
        if self.args.debug:
            print 'generating %d trees from %s' % (self.args.n_trees, parameter_dir),
            if self.args.constant_number_of_leaves:
                print ' with %s leaves' % str(self.args.n_leaves)
            else:
                print ' with random number of leaves with parameter %s' % str(self.args.n_leaves)

    #----------------------------------------------------------------------------------------
    def convert_observed_changes_to_branch_length(self, mute_freq):
        # for consistency with the rest of the code base, we call it <mute_freq> instead of "fraction of observed changes"
        # JC69 formula, from wikipedia
        # NOTE this helps, but is not sufficient, because the mutation rate is super dominated by a relative few very highly mutated positions
        argument = max(1e-2, 1. - (4./3)* mute_freq)  # HACK arbitrarily cut it off at 0.01 (only affects the very small fraction with mute_freq higher than about 0.75)
        return -(3./4) * math.log(argument)

    #----------------------------------------------------------------------------------------
    def get_mute_hist(self, mtype, parameter_dir):
        if self.args.mutate_from_scratch:
            n_entries = 500
            length_vals = [v for v in numpy.random.exponential(self.args.flat_mute_freq, n_entries)]  # count doesn't work on numpy.ndarray objects
            max_val = 0.8  # 0.5 is arbitrary, but you shouldn't be calling this with anything that gets a significant number anywhere near there, anyway
            if length_vals.count(max_val):
                print '%s lots of really high mutation rates treegenerator::get_mute_hist()' % utils.color('yellow', 'warning')
            length_vals = [min(v, max_val) for v in length_vals]
            hist = Hist(30, 0., max_val)
            for val in length_vals:
                hist.fill(val)
            hist.normalize()
        else:
            hist = Hist(fname=parameter_dir + '/' + mtype + '-mean-mute-freqs.csv')

        return hist

    #----------------------------------------------------------------------------------------
    def read_mute_freqs(self, parameter_dir):
        # NOTE these are mute freqs, not branch lengths, but it's ok for now
        branch_lengths = {}
        for mtype in ['all',] + utils.regions:
            branch_lengths[mtype] = {n : [] for n in ('lengths', 'probs')}
            mutehist = self.get_mute_hist(mtype, parameter_dir)
            branch_lengths[mtype]['mean'] = mutehist.get_mean()

            mutehist.normalize(include_overflows=False, expect_overflows=True)  # if it was written with overflows included, it'll need to be renormalized
            check_sum = 0.0
            for ibin in range(1, mutehist.n_bins + 1):  # ignore under/overflow bins
                freq = mutehist.get_bin_centers()[ibin]
                branch_length = self.convert_observed_changes_to_branch_length(float(freq))
                prob = mutehist.bin_contents[ibin]
                branch_lengths[mtype]['lengths'].append(branch_length)
                branch_lengths[mtype]['probs'].append(prob)
                check_sum += branch_lengths[mtype]['probs'][-1]
            if not utils.is_normed(check_sum):
                raise Exception('not normalized %f' % check_sum)

        if self.args.debug:
            print '  mean branch lengths'
            for mtype in ['all',] + utils.regions:
                print '     %4s %7.3f (ratio %7.3f)' % (mtype, branch_lengths[mtype]['mean'], branch_lengths[mtype]['mean'] / branch_lengths['all']['mean'])

        return branch_lengths

    #----------------------------------------------------------------------------------------
    def post_process_trees(self, treefname, lonely_leaves, ages):
        """ 
        Each tree is written with branch length the mean branch length over the whole sequence
        So we need to add the length for each region afterward, so each line looks e.g. like
        (t2:0.003751736951,t1:0.003751736951):0.001248262937;v:0.98,d:1.8,j:0.87
        """

        # first read the newick info for each tree
        with open(treefname, 'r') as treefile:
            treestrs = treefile.readlines()
        for itree in range(len(ages)):
            if lonely_leaves[itree]:
                treestrs.insert(itree, 't1:%f;\n' % ages[itree])

        # rescale branch lengths (TreeSim lets you specify the number of leaves and the height at the same time, but TreeSimGM doesn't, and TreeSim's numbers are usually a little off anyway... so we rescale everybody)
        if len(treestrs) != len(ages):
            raise Exception('expected %d trees, but read %d from %s' % (len(ages), len(treestrs), treefname))
        for itree in range(len(ages)):
            treestrs[itree] = rescale_tree(treestrs[itree], ages[itree])

        if self.args.debug:
            if self.args.debug > 1:
                print '        n-leaves       height'
            heights, n_leaves = [], []  # just for debug printing
            for itree in range(len(ages)):
                tree = get_btree(treestrs[itree])
                heights.append(sum([l.height for l in tree.leaves]) / len(tree.leaves))  # mean height -- should be the same for all of them though
                n_leaves.append(len(tree.leaves))
                if self.args.debug > 1:
                    print '       %5d         %8.6f' % (n_leaves[-1], heights[-1])
            print '    mean over %d trees:   depth %.5f   n-leaves %.2f' % (len(heights), sum(heights) / len(heights), float(sum(n_leaves)) / len(n_leaves))

        # then add the region-specific branch info
        length_list = ['%s:%f' % (region, self.branch_lengths[region]['mean'] / self.branch_lengths['all']['mean']) for region in utils.regions]
        for itree in range(len(ages)):
            treestrs[itree] = treestrs[itree].replace(';', ';' + ','.join(length_list))

        # and finally write the modified lines
        with open(treefname, 'w') as treefile:
            for line in treestrs:
                treefile.write(line + '\n')

    #----------------------------------------------------------------------------------------
    def choose_mean_branch_length(self):
        """ mean for entire sequence, i.e. weighted average over v, d, and j """
        iprob = numpy.random.uniform(0,1)
        sum_prob = 0.0
        for ibin in range(len(self.branch_lengths['all']['lengths'])):
            sum_prob += self.branch_lengths['all']['probs'][ibin]
            if iprob < sum_prob:
                return self.branch_lengths['all']['lengths'][ibin]
                
        assert False  # shouldn't fall through to here
    
    # ----------------------------------------------------------------------------------------
    def get_n_leaves(self):
        if self.args.constant_number_of_leaves:
            return self.args.n_leaves

        if self.args.n_leaf_distribution == 'geometric':
            return numpy.random.geometric(1./self.args.n_leaves)
        elif self.args.n_leaf_distribution == 'box':
            width = self.args.n_leaves / 5.  # whatever
            lo, hi = int(self.args.n_leaves - width), int(self.args.n_leaves + width)
            if hi - lo <= 0:
                raise Exception('n leaves %d and width %f round to bad box bounds [%f, %f]' % (self.args.n_leaves, width, lo, hi))
            return random.randint(lo, hi)  # NOTE interval is inclusive!
        elif self.args.n_leaf_distribution == 'zipf':
            return numpy.random.zipf(self.args.n_leaves)  # NOTE <n_leaves> is not the mean here
        else:
            raise Exception('n leaf distribution %s not among allowed choices' % self.args.n_leaf_distribution)

    # ----------------------------------------------------------------------------------------
    def generate_trees(self, seed, outfname):
        if os.path.exists(outfname):
            os.remove(outfname)

        # from TreeSim docs:
        #   frac: each tip is included into the final tree with probability frac
        #   age: the time since origin / most recent common ancestor
        #   mrca: if FALSE, time since the origin of the process, else time since the most recent common ancestor of the sampled species.
        speciation_rate = '1'
        extinction_rate = '0.5'
        n_trees_each_run = '1'
        # build command file, one (painful) tree at a time
        with tempfile.NamedTemporaryFile() as commandfile:
            commandfile.write('require(TreeSim, quietly=TRUE)\n')
            # commandfile.write('require(TreeSimGM, quietly=TRUE)\n')
            commandfile.write('set.seed(' + str(seed)+ ')\n')
            ages, lonely_leaves = [], []  # keep track of which trees should have one leaft, so we can go back and add them later in the proper spots
            for itree in range(self.args.n_trees):
                n_leaves = self.get_n_leaves()
                age = self.choose_mean_branch_length()
                ages.append(age)
                if n_leaves == 1:
                    lonely_leaves.append(True)
                    continue
                lonely_leaves.append(False)
                commandfile.write('trees <- sim.bd.taxa.age(' + str(n_leaves) + ', ' + n_trees_each_run + ', ' + speciation_rate + ', ' + extinction_rate + ', frac=1, age=' + str(age) + ', mrca = FALSE)\n')
                # commandfile.write('trees <- sim.taxa(numbsim=' + n_trees_each_run + ', ' + 'n=' + str(n_leaves) + ', distributionspname="rweibull", distributionspparameters=c(0.1, 1), labellivingsp="t")\n')
                commandfile.write('write.tree(trees[[1]], \"' + outfname + '\", append=TRUE)\n')
            commandfile.flush()
            # print '---'
            # check_call(['cat', commandfile.name])
            # print '---'
            if lonely_leaves.count(True) == len(ages):
                open(outfname, 'w').close()
            else:
                check_call('R --slave -f ' + commandfile.name, shell=True)
        self.post_process_trees(outfname, lonely_leaves, ages)
