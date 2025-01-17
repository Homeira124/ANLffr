# -*- coding: utf-8 -*-
"""
Module for preprocessing utilities. These are supposed to complement
the preproessing utilities that are available with MNE.

"""
import numpy as np

from math import ceil
from anlffr.utils import logger, verbose
from mne import pick_channels
from mne.filter import filter_data


@verbose
def find_blinks(raw, event_id=998, thresh=100e-6, l_freq=0.5, h_freq=10,
                filter_length='auto', ch_name=['A1', ], tstart=0.,
                l_trans_bandwidth=0.15):

    """Utility function to detect blink events from specified channel.

    Parameters
    ----------
    raw : instance of Raw
        The raw data.
    event_id : int
        The index to assign to found events.
    low_pass : float
        Low pass frequency.
    high_pass : float
        High pass frequency.
    filter_length : str | int | None
        Number of taps to use for filtering.
    ch_name: list | None
        If not None, use specified channel(s) for EOG
    tstart : float
        Start detection after tstart seconds.
    verbose : bool, str, int, or None
        If not None, override default verbose level (see mne.verbose).

    Returns
    -------
    eog_events : array
        Events in MNE  format, i.e., N x 3 array
    """

    sampling_rate = raw.info['sfreq']
    first_samp = raw.first_samp

    ch_eog = pick_channels(raw.ch_names, include=ch_name)

    if len(ch_eog) == 0:
        raise ValueError('%s not in channel list' % ch_name)
    else:
        logger.info('Detecting blinks from channel %s' % ch_name)

    eog, _ = raw[ch_eog, :]
    filteog = filter_data(eog, sampling_rate, l_freq, h_freq,
                          filter_length=filter_length,
                          l_trans_bandwidth=l_trans_bandwidth)

    eog_events, blinkvals = peak_finder(filteog.squeeze(), thresh=thresh)
    eog_events_neg, blinkvals_neg = peak_finder(filteog.squeeze(),
                                                thresh=thresh, extrema=-1)

    # Discarding blinks that don't look like other blinks, electing polarity
    nominal_blink = np.median(np.abs(blinkvals))
    nominal_blink_neg = np.median(np.abs(blinkvals_neg))

    if nominal_blink_neg > nominal_blink:
        blinkvals = blinkvals_neg
        nominal_blink = nominal_blink_neg
        eog_events = eog_events_neg

    eog_events = eog_events[np.logical_and(np.abs(blinkvals) < 2*nominal_blink,
                                           np.abs(blinkvals) >
                                           0.5*nominal_blink)]

    # Discarding blinks detected before tstart seconds
    eog_events = eog_events[eog_events > raw.time_as_index(tstart)]
    eog_events += first_samp
    n_events = len(eog_events)
    logger.info("Number of EOG events detected : %d" % n_events)
    eog_events = np.c_[eog_events, np.zeros(n_events),
                       event_id * np.ones(n_events)]

    return np.int64(eog_events)


@verbose
def peak_finder(x0, thresh=None, extrema=1, verbose=None):
    """Noise tolerant fast peak finding algorithm

    Parameters
    ----------
    x0 : 1d array
        A real vector from the maxima will be found (required).
    thresh : float
        The amount above surrounding data for a peak to be
        identified (default = (max(x0)-min(x0))/4). Larger values mean
        the algorithm is more selective in finding peaks.
    extrema : {-1, 1}
        1 if maxima are desired, -1 if minima are desired
        (default = maxima, 1).
    verbose : bool, str, int, or None
        If not None, override default verbose level (see mne.verbose).

    Returns
    -------
    peak_loc : array
        The indices of the identified peaks in x0
    peak_mag : array
        The magnitude of the identified peaks

    Note
    ----
    If repeated values are found the first is identified as the peak.
    Conversion from initial Matlab code from:
    Nathanael C. Yoder (ncyoder@purdue.edu)

    Example
    -------
    t = 0:.0001:10;
    x = 12*sin(10*2*pi*t)-3*sin(.1*2*pi*t)+randn(1,numel(t));
    x(1250:1255) = max(x);
    peak_finder(x)
    """

    x0 = np.asanyarray(x0)

    if x0.ndim >= 2:
        raise ValueError('The input data must be a 1D vector')

    s = x0.size

    if thresh is None:
        thresh = (np.max(x0) - np.min(x0)) / 4

    assert extrema in [-1, 1]

    if extrema == -1:
        x0 = extrema * x0  # Make it so we are finding maxima regardless

    dx0 = np.diff(x0)  # Find derivative
    # This is so we find the first of repeated values
    dx0[dx0 == 0] = -np.finfo(float).eps
    # Find where the derivative changes sign
    ind = np.where(dx0[:-1:] * dx0[1::] < 0)[0] + 1

    # Include endpoints in potential peaks and valleys
    x = np.concatenate((x0[:1], x0[ind], x0[-1:]))
    ind = np.concatenate(([0], ind, [s - 1]))

    #  x only has the peaks, valleys, and endpoints
    length = x.size
    min_mag = np.min(x)

    if length > 2:  # Function with peaks and valleys

        # Set initial parameters for loop
        temp_mag = min_mag
        found_peak = False
        left_min = min_mag

        # Deal with first point a little differently since tacked it on
        # Calculate the sign of the derivative since we taked the first point
        # on it does not necessarily alternate like the rest.
        signDx = np.sign(np.diff(x[:3]))
        if signDx[0] <= 0:  # The first point is larger or equal to the second
            ii = -1
            if signDx[0] == signDx[1]:  # Want alternating signs
                x = np.concatenate((x[:1], x[2:]))
                ind = np.concatenate((ind[:1], ind[2:]))
                length -= 1

        else:  # First point is smaller than the second
            ii = 0
            if signDx[0] == signDx[1]:  # Want alternating signs
                x = x[1:]
                ind = ind[1:]
                length -= 1

        # Preallocate max number of maxima
        maxPeaks = int(ceil(length / 2.0))
        peak_loc = np.zeros(maxPeaks, dtype=int)
        peak_mag = np.zeros(maxPeaks)
        c_ind = 0
        # Loop through extrema which should be peaks and then valleys
        while ii < (length - 1):
            ii += 1  # This is a peak
            # Reset peak finding if we had a peak and the next peak is bigger
            # than the last or the left min was small enough to reset.
            if found_peak and ((x[ii] > peak_mag[-1]) or
                               (left_min < peak_mag[-1] - thresh)):
                temp_mag = min_mag
                found_peak = False

            # Make sure we don't iterate past the length of our vector
            if ii == length - 1:
                break  # We assign the last point differently out of the loop

            # Found new peak that was lager than temp mag and threshold larger
            # than the minimum to its left.
            if (x[ii] > temp_mag) and (x[ii] > left_min + thresh):
                temp_loc = ii
                temp_mag = x[ii]

            ii += 1  # Move onto the valley
            # Come down at least thresh from peak
            if not found_peak and (temp_mag > (thresh + x[ii])):
                found_peak = True  # We have found a peak
                left_min = x[ii]
                peak_loc[c_ind] = temp_loc  # Add peak to index
                peak_mag[c_ind] = temp_mag
                c_ind += 1
            elif x[ii] < left_min:  # New left minima
                left_min = x[ii]

        # Check end point
        if (x[-1] > temp_mag) and (x[-1] > (left_min + thresh)):
            peak_loc[c_ind] = length - 1
            peak_mag[c_ind] = x[-1]
            c_ind += 1
        elif not found_peak and temp_mag > min_mag:
            # Check if we still need to add the last point
            peak_loc[c_ind] = temp_loc
            peak_mag[c_ind] = temp_mag
            c_ind += 1

        # Create output
        peak_inds = ind[peak_loc[:c_ind]]
        peak_mags = peak_mag[:c_ind]
    else:  # This is a monotone function where an endpoint is the only peak
        x_ind = np.argmax(x)
        peak_mags = x[x_ind]
        if peak_mags > (min_mag + thresh):
            peak_inds = ind[x_ind]
        else:
            peak_mags = []
            peak_inds = []

    # Change sign of data if was finding minima
    if extrema < 0:
        peak_mags *= -1.0
        x0 = -x0

    # Plot if no output desired
    if len(peak_inds) == 0:
        logger.info('No significant peaks found')

    return peak_inds, peak_mags
