# -*- coding: utf-8 -*-
from __future__ import absolute_import
from typing import Optional, Tuple, List

import numpy as np # type: ignore
import keras # type: ignore
import keras.backend as K # type: ignore
from keras.models import Model # type: ignore
from keras.layers import Layer # type: ignore


def gradcam_backend_keras(model, # type: Model
    doc, # type: np.ndarray
    targets, # type: Optional[List[int]]
    activation_layer, # type: Layer
    ):
    # type: (...) -> Tuple[np.ndarray, np.ndarray, int, float]
    """
    Compute the terms and by-products required by the Grad-CAM formula.
    
    Parameters
    ----------
    model : keras.models.Model
        Differentiable network.

    doc : numpy.ndarray
        Input to the network.

    targets : list, optional
        Index into the network's output,
        indicating the output node that will be
        used as the "loss" during differentiation.

    activation_layer : keras.layers.Layer
        Keras layer instance to differentiate with respect to.
    

    See :func:`eli5.keras.explain_prediction` for description of the 
    ``model``, ``doc``, ``targets`` parameters.

    Returns
    -------
    # FIXME: long line
    (activations, gradients, predicted_idx, predicted_val) : (numpy.ndarray, numpy.ndarray, int, float)
        Values of variables.
    """
    # score for class in targets
    # TODO: maybe do the sum / loss calculation in this function and pass it to gradcam.
    # This would be consistent with what is done in
    # https://github.com/ramprs/grad-cam/blob/master/misc/utils.lua
    # and https://github.com/ramprs/grad-cam/blob/master/classification.lua
    # TODO: as in pytorch PR, separate out classification tensor code
    if targets is not None:
        predicted_idx = _get_target_prediction(targets, model)
    else:
        predicted_idx = _autoget_target_prediction(model)
    predicted_val = K.gather(model.output[0, :], predicted_idx) # access value by index

    # output of target activation layer, i.e. activation maps of a convolutional layer
    activation_output = activation_layer.output 

    # score for class w.r.p.t. activation layer
    grads = _calc_gradient(predicted_val, [activation_output])

    output = model.output

    # TODO: gradcam on input layer
    evaluate = K.function([model.input], 
        [activation_output, grads, predicted_val, predicted_idx, output]
    )
    # evaluate the graph / do actual computations
    activations, grads, predicted_val, predicted_idx, output = evaluate([doc])

    # put into suitable form
    # FIXME: batch assumptions should be removed
    predicted_val = predicted_val[0]
    predicted_idx = predicted_idx[0]
    return activations, grads, predicted_idx, predicted_val


def _calc_gradient(ys, xs):
    # (K.variable, list) -> K.variable
    # FIXME: K.variable is not the right type to use?
    """
    Return the gradient of scalar ``ys`` with respect to each of list ``xs``,
    (must be singleton)
    and apply grad normalization.
    """
    # differentiate ys (scalar) with respect to each variable in xs
    # K.gradients tends to produce bigger values than tf.gradients
    # Note that gradients also point to the direction of the greatest increase in ys
    # Meaning that the class score is maximized if we move in the direction of the gradient.
    grads = K.gradients(ys, xs)

    # grads gives a python list with a tensor (containing the derivatives) for each xs
    # to use grads with other operations and with K.function
    # we need to work with the actual tensors and not the python list
    grads, = grads # grads should be a singleton list (because xs is a singleton)

    # validate that the gradients were calculated successfully (no None's)
    # https://github.com/jacobgil/keras-grad-cam/issues/17#issuecomment-423057265
    # https://github.com/tensorflow/tensorflow/issues/783#issuecomment-175824168
    if grads is None:
        raise ValueError('Gradient calculation resulted in None values. '
                         'Check that the model is differentiable and try again. '
                         'ys: {}. xs: {}. grads: {}'.format(
                            ys, xs, grads))

    # this seems to make the heatmap less noisy
    grads =  K.l2_normalize(grads) 
    return grads


def _get_target_prediction(targets, model):
    # type: (list, Model) -> K.variable
    """
    Get a prediction ID based on ``targets``, 
    from the model ``model`` (with a rank 2 tensor for its final layer).
    Returns a rank 1 K.variable tensor.
    """
    if isinstance(targets, list):
        # take the first prediction from the list
        if len(targets) == 1:
            target = targets[0]
            _validate_target(target, model.output_shape)
            return K.constant([target], dtype='int64')
        else:
            raise ValueError('More than one prediction target '
                             'is currently not supported ' 
                             '(found a list that is not length 1): '
                             '{}'.format(targets))
    else:
        raise TypeError('Invalid argument "targets" (must be list or None): %s' % targets)


def _autoget_target_prediction(model):
    # type: (Model) -> K.variable
    """Automatically get the highest value prediction from ``model``"""
    output = model.output
    return K.argmax(output, axis=-1)


# FIXME: should this be moved to general gradcam package?
def _validate_target(target, output_shape):
    # type: (int, tuple) -> None
    """
    Check whether ``target``, 
    an integer index into the model's output
    is valid for the given ``output_shape``.
    """
    if isinstance(target, int):
        output_nodes = output_shape[1:][0]
        if not (0 <= target < output_nodes):
            raise ValueError('Prediction target index is ' 
                             'outside the required range [0, {}). ',
                             'Got {}'.format(output_nodes, target))
    else:
        raise TypeError('Prediction target must be int. '
                        'Got: {}'.format(target))