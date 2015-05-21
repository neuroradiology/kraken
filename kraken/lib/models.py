"""
kraken.lib.models
~~~~~~~~~~~~~~~~~

Wraps around legacy pyrnn and HDF5 models to provide a single interface. In the
future it will also include support for clstm models.
"""

from __future__ import absolute_import

import h5py
import numpy
import cPickle
import gzip
import bz2
import sys

import kraken.lib.lstm
import kraken.lib.lineest

from kraken.lib.lineest import CenterNormalizer
from kraken.lib.exceptions import KrakenInvalidModelException

def load_hdf5(fname, hiddensize=100):
    """
    Loads a model in HDF5 format and instantiates a
    kraken.lib.lstm.SeqRecognizer object.

    Args:
        fname (unicode): Path to the HDF5 file
        hiddensize (int): # LSTM state units

    Returns:
        A kraken.lib.lstm.SeqRecognizer object
    """
    with h5py.File(fname, 'r') as rnn:
        # first extract the codec character set
        charset = [unichr(x) for x in rnn.get('codec')]
        # code 0 is handled separately by the model
        charset[0] = ''
        codec = kraken.lib.lstm.Codec().init(charset)

        # next build a line estimator 
        lnorm = lineest.CenterNormalizer(lineheight)
        network = kraken.lib.lstm.SeqRecognizer(lnorm.target_height, 
                                     hiddensize, 
                                     codec = codec, 
                                     normalize = kraken.lib.lstm.normalize_nfkc)
        parallel, softmax = network.lstm.nets
        nornet, rev = parallel.nets
        revnet = rev.net
        for w in ('WGI', 'WGF', 'WGO', 'WCI', 'WIP', 'WFP', 'WOP'):
            setattr(nornet, w, f['.bidilstm.0.parallel.0.lstm.' +
                    w][:].reshape(getattr(nornet, w).shape))
            setattr(revnet, w, f['.bidilstm.0.parallel.1.reversed.0.lstm.' +
                    w][:].reshape(getattr(nornet, w).shape))
        softmax.W2 = numpy.hstack((f['.bidilstm.1.softmax.w'][:],
                                   f['.bidilstm.1.softmax.W'][:]))
        network.lnorm = lnorm
        return network

def load_pyrnn(fname):
    """
    Loads a legacy RNN from a pickle file.

    Args:
        fname (unicode): Path to the pickle object

    Returns:
        Unpickled object

    """

    def find_global(mname, cname):
        aliases = {
            'lstm.lstm': kraken.lib.lstm,
            'ocrolib.lstm': kraken.lib.lstm,
            'ocrolib.lineest': kraken.lib.lineest,
        }
        if mname in aliases:
            return getattr(aliases[mname], cname)
        return getattr(sys.modules[mname], cname)

    of = open
    if fname.endswith(u'.gz'):
        of = gzip.open
    elif fname.endswith(u'.bz2'):
        of = bz2.BZ2File
    with of(fname, 'rb') as fp:
        unpickler = cPickle.Unpickler(fp)
        unpickler.find_global = find_global
        try:
            rnn = unpickler.load()
        except cPickle.UnpicklingError as e:
            raise KrakenInvalidModelException(e.message)
        if not isinstance(rnn, kraken.lib.lstm.SeqRecognizer):
            raise KrakenInvalidModelException('Pickle is %s instead of '
                                              'SeqRecognizer' %
                                              type(rnn).__name__)
        return rnn

def pyrnn_to_hdf5(pyrnn=None, output='en-default.hdf5'):
    """
    Converts a legacy python RNN to the new HDF5 format. Benefits of the new
    format include independence from particular python versions and no
    arbitrary code execution issues inherent in pickle.

    Args:
        pyrnn (kraken.lib.lstm.SegRecognizer): pyrnn model
        output (unicode): path of the converted HDF5 model
    """

    parallel, softmax = pyrnn.lstm.nets
    fwdnet, revnet = parallel.nets
    
    with h5py.File(output, 'w') as nf:
        for w in ('WGI', 'WGF', 'WGO', 'WCI'):
            dset = nf.create_dataset(".bidilstm.0.parallel.0.lstm." + w,
                                     getattr(fwdnet, w).shape, dtype='f')
            dset[...] = getattr(fwdnet, w)
            dset = nf.create_dataset(".bidilstm.0.parallel.1.reversed.0.lstm." + w,
                                     getattr(revnet.net, w).shape, dtype='f')
            dset[...] = getattr(revnet.net, w)

        for w in ('WIP', 'WFP', 'WOP'):
            data = getattr(fwdnet, w).reshape((-1, 1))
            dset = nf.create_dataset(".bidilstm.0.parallel.0.lstm." + w,
                                     data.shape, dtype='f')
            dset[...] = data
            
            data = getattr(revnet.net, w).reshape((-1, 1))
            dset = nf.create_dataset(".bidilstm.0.parallel.1.reversed.0.lstm." + w,
                                     data.shape, dtype='f')
            dset[...] = data

        dset = nf.create_dataset(".bidilstm.1.softmax.w",
                                 (softmax.W2[:,0].shape[0], 1), dtype='f')
        dset[:] = softmax.W2[:,0].reshape((-1, 1))

        dset = nf.create_dataset(".bidilstm.1.softmax.W", softmax.W2[:,1:].shape,
                                 dtype='f')
        dset[:] = softmax.W2[:,1:]
        cvals = pyrnn.codec.code2char.itervalues()
        cvals.next()
        codec = numpy.array([0]+[ord(x) for x in cvals], dtype='f').reshape((-1, 1))
        dset = nf.create_dataset("codec", codec, dtype='f')
        dset[:] = codec