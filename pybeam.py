#!/usr/bin/python

import numpy as np
import scipy.signal
import scipy.io.wavfile
import os
import sys
import shutil
import pickle as pkl
import wave
import pyaudio as pa
import matplotlib.pyplot as plt

__c = 343 #speed of sound
__l2 = lambda arr: np.sqrt(np.sum(arr**2))
__Zf = lambda x_m, y_l, omega: np.e**(-1j * omega / __c * __l2(x_m - y_l)) / (4 * np.pi * __l2(x_m - y_l))

def get_source_matrix(dim=(2, 1), delta=(0.5, 0), center=(0, 0, 0)):
    L = dim[0] * dim[1]
    y = np.zeros((L, 3))
    for x in range(dim[0]):
        for z in range(dim[1]):
            y[x * dim[1] + z] = np.array([center[0] + (x-dim[0]//2+0.5)*delta[0],
                                    center[1],
                                    center[2] + (z-dim[1]//2+0.5)*delta[1]])
    return y

def get_verification_matrix(R=3, dim=(37,1), b=(90,90)):
    M = dim[0] * dim[1]
    delta_theta = 180 / (dim[0] - 1) * np.pi / 180 if dim[0] > 1 else 0 
    delta_phi = 180 / (dim[1] - 1) * np.pi / 180 if dim[1] > 1 else 0
    xtmp = np.zeros((M, 3))
    bidx, mindist, targpoint = -1, float('inf'), np.array([R*np.sin(np.radians(b[1]))*np.cos(np.radians(b[0])),
            R*np.sin(np.radians(b[1]))*np.sin(np.radians(b[0])),
            R*np.cos(np.radians(b[1]))])
    if dim[0] <= 1: #semicircle with variable phi
        for j in range(dim[1]):
            xtmp[j] = np.array([0, R*np.sin(j*delta_phi), R*np.cos(j*delta_phi)])
            if __l2(xtmp[j] - targpoint) < mindist:
                bidx = j
                mindist = __l2(xtmp[j] - targpoint)
    elif dim[1] <= 1: #semicircle with variable theta
        for i in range(dim[0]):
            xtmp[i] = np.array([R*np.cos(i*delta_theta), R*np.sin(i*delta_theta), 0])
            if __l2(xtmp[i] - targpoint) < mindist:
                bidx = i
                mindist = __l2(xtmp[i] - targpoint)
    else: #full hemisphere
        for i in range(dim[0]):
            for j in range(dim[1]):
                idx = i * dim[1] + j
                xtmp[idx] = np.array([R*np.cos(i*delta_theta)*np.sin(j*delta_phi),
                                R*np.sin(i*delta_theta)*np.sin(j*delta_phi),
                                R*np.cos(j*delta_phi)])
                if __l2(xtmp[idx] - targpoint) < mindist:
                    bidx = idx
                    mindist = __l2(xtmp[idx] - targpoint)
    x = xtmp.copy()
    x[0], x[1:bidx+1] = xtmp[bidx], xtmp[:bidx]
    return x

def get_DAS_filters(X=get_verification_matrix(), Y=get_source_matrix(), 
    samp_freq=44100, samples=1024, modeling_delay=0):
        M, L = X.shape[0], Y.shape[0]
        gamma = lambda x_b, y, l: 16 * np.pi**2 * __l2(x_b - y[l])**2 / L
        freqs = np.fft.fftfreq(samples, 1 / samp_freq)
        q_DAS = np.asmatrix(np.zeros((freqs.size, L), dtype="complex_"))
        
        for i in range(freqs.size):
            freq = freqs[i]
            omega = 2 * np.pi * freq
            z_b = np.asmatrix(np.zeros((L,1)), dtype="complex_")
            for l in range(L):
                z_b[l, 0] = __Zf(X[0], Y[l], omega)
            Gamma = np.asmatrix(np.zeros((L,L)), dtype="complex_")
            for l in range(L):
                Gamma[l,l] = gamma(X[0], Y, l)
            this_q = np.e**(-1j * omega * modeling_delay) * Gamma * np.conjugate(z_b)
            q_DAS[i] = this_q.T

        return q_DAS

def get_max_energy(sigma=5, R=3, Y=get_source_matrix()):
    return sigma * (4 * np.pi * R)**2 / Y.shape[0]
    
def get_target_sound_pressures(onval=1, offval=0, X=get_verification_matrix()):
    return np.asmatrix(np.array([onval] + [offval]*(X.shape[0]-1), dtype="complex_")).T

def get_PM_filters(X=get_verification_matrix(), Y=get_source_matrix(),
    samp_freq=44100, samples=1024, modeling_delay=0, 
    E_max=get_max_energy(), p_hat=get_target_sound_pressures(),
    verbose=False):
        M, L, p_b_hat = X.shape[0], Y.shape[0], p_hat[0]
        W = lambda q, z_b: (p_b_hat / np.dot(z_b, q))[0, 0]
        E = lambda q: np.dot(np.conjugate(q).T, q)[0, 0]
        epsilon_beta, beta_min = 1e-5, 1e-19
        freqs = np.fft.fftfreq(samples, 1 / samp_freq)
        q_PM = np.asmatrix(np.zeros((freqs.size, L), dtype="complex_"))

        for i in range(len(freqs)):
            freq = freqs[i]
            if(verbose): print('frequency:', freq, flush=True)
            omega = 2 * np.pi * freq
            beta = beta_min
            Z = np.asmatrix(np.zeros((M, L), dtype="complex_"))
            for m in range(M):
                for l in range(L):
                    Z[m, l] = __Zf(X[m], Y[l], omega)
            q_temp = np.linalg.inv(
                np.conjugate(Z).T * Z + beta * np.asmatrix(np.eye(L))) \
                * np.conjugate(Z).T * p_hat
            q_hat = W(q_temp, Z[0]) * q_temp
            while(E(q_hat) > E_max):
                beta += epsilon_beta
                q_temp = np.linalg.inv(
                    np.conjugate(Z).T * Z + beta * np.asmatrix(np.eye(L))) \
                    * np.conjugate(Z).T * p_hat
                q_hat = W(q_temp, Z[0]) * q_temp
            q_PM[i] = np.e**(-1j * omega * modeling_delay) * q_hat.T
                
        return q_PM    
        
def map_filters(filters, signal):
    
    #beamforming filters
    samples, L = filters.shape[0], filters.shape[1]
    o = np.zeros((L, len(signal)), dtype="complex_")
    for i in range(0, len(signal), samples//4):
        snapshot = np.pad(signal[i:i+samples],
                    (0, samples - len(signal[i:i+samples])),
                    'constant',
                    constant_values=0)
        snapshot_fft = np.fft.fft(snapshot)
        for l in range(L):
            snapshot_filt = np.multiply(snapshot_fft, filters[:, l].T)
            o[l, i:i+min(samples, len(o[l]) - i)] = \
                np.fft.ifft(snapshot_filt)[:, :min(samples, len(o[l]) - i)]
    abs_avgs = np.average(np.abs(o), axis=1)
    max_avg = abs_avgs[np.argmax(abs_avgs)]
    scaling_factor = np.average(np.abs(signal)) / max_avg
    o *= scaling_factor
    
    #butterworth filter
    filtb, filta = scipy.signal.butter(8, 0.5)
    o = scipy.signal.filtfilt(filtb, filta, o)
    o = o.real.astype(signal.dtype)

    return o

def read_wav_file(fname):
    ret1 = scipy.io.wavfile.read(fname)
    ret2 = ret1[1].dtype
    return ret1[1], ret1[0], ret2

def write_wav_dir(directory, output_signal, mapping, samp_freq=44100):
    if os.path.exists(directory):
        shutil.rmtree(directory)
    os.mkdir(directory)
    for i in range(0, output_signal.shape[0], 2):
        scipy.io.wavfile.write('{}/speaker{:d}.wav'.format(directory, i//2),
            samp_freq,
            output_signal[i:i+2].T)
    pkl.dump(mapping, open('{}/mapping.pkl'.format(directory), 'wb'))

#mapping = speaker pair # -> input id

def playback_wav_dir(directory, chunks=1024):
   
    #read mapping
    mapping = pkl.load(open('{}/mapping.pkl'.format(directory), 'rb'))
    nstreams = len(mapping)
    p = pa.PyAudio()
    
    #read wav files
    wfiles = {}
    for i in range(nstreams):
        wavfile = wave.open('{}/speaker{:d}.wav'.format(directory, i), 'rb')
        wfiles[mapping[i]] = wavfile
    
    #create streams
    streams = {}
    for i in range(nstreams):
        streams[mapping[i]] = p.open(
            format=p.get_format_from_width(wfiles[mapping[i]].getsampwidth()),
            channels=wfiles[mapping[i]].getnchannels(),
            rate=wfiles[mapping[i]].getframerate(),
            output=True,
            output_device_index=mapping[i])
    
    #playback wav files
    data = [wfiles[mapping[i]].readframes(chunks) for i in range(nstreams)]
    while not all([len(data[i]) == 0 for i in range(nstreams)]):
        #print([len(_) for _ in data])
        for i in range(nstreams): streams[mapping[i]].write(data[i])
        data = [wfiles[mapping[i]].readframes(chunks) for i in range(nstreams)]
    #print([len(_) for _ in data])

    #close up shop
    for i in range(nstreams):
        streams[mapping[i]].stop_stream()
        streams[mapping[i]].close()
    p.terminate()

def visualize(Q, X, Y, onval=1, R=3, test_index=100, 
    dpu=100, sample_size=1024, rate=44100, verbose=False):
        M, L = X.shape[0], Y.shape[0]
        M_test = int((R+1)**2 * dpu**2 * 2)
        if(verbose): print(M_test)
        X_test = np.ones((M_test, 3))
        n = 0
        for i in range(-dpu * (R+1), dpu * (R+1)):
            for j in range(0, dpu * (R+1)):
                X_test[n] = np.array([i / dpu, j / dpu, 0])
                n += 1 
        Z = np.asmatrix(np.zeros((M_test, L), dtype='complex_'))
        freq = np.fft.fftfreq(sample_size, 1 / rate)[test_index]
        omega = 2 * np.pi * freq
        if(verbose): 
            print('Freq:{:.0f}, AngVel:{:.0f}'.format(freq, omega), flush=True)
        for m in range(M_test):
            if m % 10000 == 0 and verbose: print(m, M_test, flush=True)
            for l in range(L):
                if __l2(X_test[m] - Y[l]) != 0:
                    Z[m, l] = __Zf(X_test[m], Y[l], omega)
                else:
                    Z[m, l] = 0
        p_test = Z * Q[test_index].T
        

        output = np.zeros(((R+1)*dpu, 2*(R+1)*dpu))
        for n in range(X_test.shape[0]):
            output[(R+1)*dpu - 1 - int(X_test[n, 1]*dpu), int(X_test[n, 0] * dpu + (R+1)*dpu)] = np.abs(p_test[n, 0])
        for i in range(output.shape[0]):
            for j in range(output.shape[1]):
                if output[i, j] == 0:
                    denom = 0
                    if i + 1 < output.shape[0] and output[i + 1, j] != 0:
                        output[i, j] += output[i + 1, j]
                        denom += 1
                    if i - 1 >= 0 and output[i - 1, j] != 0:
                        output[i, j] += output[i - 1, j]
                        denom += 1
                    if j + 1 < output.shape[1] and output[i, j + 1] != 0:
                        output[i, j] += output[i, j + 1]
                        denom += 1
                    if j - 1 >= 0 and output[i, j - 1] != 0:
                        output[i, j] += output[i, j - 1]
                        denom += 1
                    if denom > 0:    
                        output[i, j] /= denom
        fig = plt.figure()
        plt.scatter(np.asarray(np.concatenate((X, Y))[:, 0]), 
            np.concatenate((X, Y))[:, 1], 
            c=['b'] + ['r']*(M-1) + ['g']*L, marker='o')
        implot = plt.imshow(output, interpolation='hamming', cmap='inferno', extent=[-R-1, R+1, 0, R+1], vmin=0, vmax=onval)
        plt.colorbar()
        plt.title("{:.0f}Hz".format(freq), fontsize=32)
        plt.xlabel("x, [m]", fontsize=12)
        plt.ylabel("y, [m]", fontsize=12)
        plt.show()
    
    

if __name__ == '__main__':
    print('Y =', get_source_matrix())
    print('X =', get_verification_matrix())
    print('q_DAS =', get_DAS_filters())
    print('q_PM =', get_PM_filters())
    
