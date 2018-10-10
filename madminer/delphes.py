from __future__ import absolute_import, division, print_function, unicode_literals

import six
from collections import OrderedDict
import numpy as np
import logging

from madminer.utils.interfaces.hdf5 import save_events_to_madminer_file, load_benchmarks_from_madminer_file
from madminer.utils.interfaces.delphes import run_delphes
from madminer.utils.interfaces.root import extract_observables_from_delphes_file
from madminer.utils.interfaces.hepmc import extract_weight_order
from madminer.utils.various import general_init


class DelphesProcessor:
    """ """

    def __init__(self, filename=None, debug=False):
        """ Constructor """

        general_init(debug=debug)

        # Initialize samples
        self.hepmc_sample_filenames = []
        self.delphes_sample_filenames = []
        self.hepmc_sample_weight_labels = []
        self.hepmc_sampled_from_benchmark = []

        # Initialize observables
        self.observables = OrderedDict()
        self.observables_required = OrderedDict()
        self.observables_defaults = OrderedDict()

        # Initialize cuts
        self.cuts = []
        self.cuts_default_pass = []

        # Initialize samples
        self.observations = None
        self.weights = None

        # Information from .h5 file
        self.filename = filename
        if self.filename is None:
            self.benchmark_names = None
        else:
            self.benchmark_names = load_benchmarks_from_madminer_file(self.filename)

    def add_hepmc_sample(self, filename, sampled_from_benchmark):

        logging.info('Adding HepMC sample at %s', filename)

        self.hepmc_sample_filenames.append(filename)
        self.hepmc_sample_weight_labels.append(
            extract_weight_order(filename, sampled_from_benchmark)
        )

    def run_delphes(self, delphes_directory, delphes_card, initial_command=None, log_directory=None):


        if log_directory is None:
            log_directory = './logs'
        log_file = log_directory + '/delphes.log'

        for hepmc_sample_filename in self.hepmc_sample_filenames:
            logging.info('Running Delphes (%s) on event sample at %s', delphes_directory, hepmc_sample_filename)
            delphes_sample_filename = run_delphes(
                delphes_directory,
                delphes_card,
                hepmc_sample_filename,
                initial_command=initial_command,
                log_file=log_file
            )
            self.delphes_sample_filenames.append(delphes_sample_filename)

    def add_delphes_sample(self, filename):

        raise NotImplementedError('Direct use of Delphes samples is currently disabled since the Delphes file alone '
                                  'does not contain any information linking the weights to the benchmarks ')

        # logging.info('Adding Delphes sample at %s', filename)
        # self.delphes_sample_filenames.append(filename)

    def add_observable(self, name, definition, required=False, default=None):

        if required:
            logging.debug('Adding required observable %s = %s', name, definition)
        else:
            logging.debug('Adding optional observable %s = %s with default %s', name, definition, default)

        self.observables[name] = definition
        self.observables_required[name] = required
        self.observables_defaults[name] = default

    def read_observables_from_file(self, filename):
        raise NotImplementedError

    def add_default_observables(
            self,
            n_leptons_max=2,
            n_photons_max=2,
            n_jets_max=2,
            include_met=True
    ):
        # ETMiss
        if include_met:
            self.add_observable(
                'et_miss',
                'met.pt',
                required=True
            )
            self.add_observable(
                'phi_miss',
                'met.phi()',
                required=True
            )

        # Observed particles
        for n, symbol in zip([n_leptons_max, n_photons_max, n_jets_max], ['l', 'a', 'j']):
            self.add_observable(
                'n_{}s'.format(symbol),
                'len({})'.format(symbol),
                required=True
            )

            for i in range(n):
                self.add_observable(
                    'e_{}{}'.format(symbol, i + 1),
                    '{}[{}].pt'.format(symbol, i),
                    required=False,
                    default=0.
                )
                self.add_observable(
                    'pt_{}{}'.format(symbol, i + 1),
                    '{}[{}].e'.format(symbol, i),
                    required=False,
                    default=0.
                )
                self.add_observable(
                    'eta_{}{}'.format(symbol, i + 1),
                    '{}[{}].eta'.format(symbol, i),
                    required=False,
                    default=0.
                )
                self.add_observable(
                    'phi_{}{}'.format(symbol, i + 1),
                    '{}[{}].phi()'.format(symbol, i),
                    required=False,
                    default=0.
                )

    def add_cut(self, definition, pass_if_not_parsed=False):
        logging.info('Adding cut %s', definition)
        self.cuts.append(definition)
        self.cuts_default_pass.append(pass_if_not_parsed)

    def analyse_delphes_samples(self):

        n_benchmarks = None if self.benchmark_names is None else len(self.benchmark_names)

        for delphes_file, weight_labels in zip(self.delphes_sample_filenames, self.hepmc_sample_weight_labels):

            logging.info('Analysing Delphes sample %s', delphes_file)

            # Calculate observables and weights in Delphes ROOT file
            this_observations, this_weights = extract_observables_from_delphes_file(
                delphes_file,
                self.observables,
                self.observables_required,
                self.observables_defaults,
                self.cuts,
                self.cuts_default_pass,
                weight_labels
            )

            # Number of benchmarks
            if n_benchmarks is None:
                n_benchmarks = len(this_weights)

            # Background scenario: we only have one set of weights, but these should be true for all benchmarks
            if len(this_weights) == 1 and self.benchmark_names is not None:
                original_weights = list(six.itervalues(this_weights))[0]

                this_weights = OrderedDict()
                for benchmark_name in self.benchmark_names:
                    this_weights[benchmark_name] = original_weights

            # First results
            if self.observations is None and self.weights is None:
                self.observations = this_observations
                self.weights = this_weights
                continue

            # Following results: check consistency with previous results
            if len(self.weights) != len(this_weights):
                raise ValueError("Number of weights in different Delphes files incompatible: {} vs {}".format(
                    len(self.weights), len(this_weights)
                ))
            if len(self.observations) != len(this_observations):
                raise ValueError("Number of observations in different Delphes files incompatible: {} vs {}".format(
                    len(self.observations), len(this_observations)
                ))

            # Merge results with previous
            for key in self.weights:
                assert key in this_weights, "Weight label {} not found in Delphes sample!".format(
                    key
                )
                self.weights[key] = np.hstack([self.weights[key], this_weights[key]])

            for key in self.observations:
                assert key in this_observations, "Observable {} not found in Delphes sample!".format(
                    key
                )
                self.observations[key] = np.hstack([self.observations[key], this_observations[key]])

    def save(self, filename_out):

        assert (self.observables is not None and self.observations is not None
                and self.weights is not None), 'Nothing to save!'

        if self.filename is None:
            logging.info('Saving HDF5 file to %s', filename_out)
        else:
            logging.info('Loading HDF5 data from %s and saving file to %s', self.filename, filename_out)

        save_events_to_madminer_file(filename_out,
                                     self.observables,
                                     self.observations,
                                     self.weights,
                                     copy_from=self.filename)
