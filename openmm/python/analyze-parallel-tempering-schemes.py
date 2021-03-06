#!/usr/local/bin/env python

#=============================================================================================
# MODULE DOCSTRING
#=============================================================================================

"""
Analyze alanine dipeptide 2D PMF via replica exchange.

DESCRIPTION



COPYRIGHT

@author John D. Chodera <jchodera@gmail.com>

This source file is released under the GNU General Public License.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.
 
You should have received a copy of the GNU General Public License along with
this program.  If not, see <http://www.gnu.org/licenses/>.

"""

#=============================================================================================
# GLOBAL IMPORTS
#=============================================================================================

import scipy.optimize # THIS MUST BE IMPORTED FIRST?!

import os
import os.path

import numpy
import math
import time

import simtk.unit as units

import netCDF4 as netcdf # netcdf4-python is used in place of scipy.io.netcdf for now

try:
    import timeseries
except:
    raise Exception("The pymbar Python package must be installed.")

#=============================================================================================
# SOURCE CONTROL
#=============================================================================================

__version__ = "$Id: $"

#=============================================================================================
# SUBROUTINES
#=============================================================================================

def compute_torsion(coordinates, i, j, k, l):
    """
    Compute torsion angle defined by four atoms.
    
    ARGUMENTS
    
    coordinates (simtk.unit.Quantity wrapping numpy natoms x 3) - atomic coordinates
    i, j, k, l - four atoms defining torsion angle
    
    NOTES
    
    Algorithm of Swope is used.    
    
    """
    rji = (coordinates[i,:] - coordinates[j,:]) / units.angstroms
    rjk = (coordinates[k,:] - coordinates[j,:]) / units.angstroms
    rkj = (coordinates[j,:] - coordinates[k,:]) / units.angstroms
    rkl = (coordinates[l,:] - coordinates[k,:]) / units.angstroms
    n1 = numpy.cross(rji, rjk); n1 = n1 / numpy.sqrt(numpy.dot(n1, n1))
    n2 = numpy.cross(rkl, rkj); n2 = n2 / numpy.sqrt(numpy.dot(n2, n2))
    cos_theta = numpy.dot(n1, n2)
    if (abs(cos_theta) > 1.0):
        cos_theta = 1.0 * numpy.sign(cos_theta)
    if math.isnan(cos_theta):
        print "cos_theta is NaN"
    if math.isnan(numpy.arccos(cos_theta)):
        print "arccos(cos_theta) is NaN"
        print "cos_theta = %f" % cos_theta
        print coordinates[i,:]
        print coordinates[j,:]
        print coordinates[k,:]
        print coordinates[l,:]
        print "n1"
        print n1
        print "n2"
        print n2
    theta = numpy.arccos(cos_theta) * units.radians
    
    if (numpy.dot(rjk, numpy.cross(n1, n2)) < 0.0):
        theta = - theta
    return theta

def show_mixing_statistics(ncfile, show_transition_matrix=False):
    """
    Print summary of mixing statistics.

    ARGUMENTS
      ncfile - NetCDF file handle
    
    """

    print "Computing mixing statistics..."

    states = ncfile.variables['states'][:,:].copy()

    # Determine number of iterations and states.
    [niterations, nstates] = ncfile.variables['states'][:,:].shape

    # Compute statistics of transitions.
    Nij = numpy.zeros([nstates,nstates], numpy.float64)
    for iteration in range(niterations-1):
        for ireplica in range(nstates):
            istate = states[iteration,ireplica]
            jstate = states[iteration+1,ireplica]
            Nij[istate,jstate] += 0.5
            Nij[jstate,istate] += 0.5
    Tij = numpy.zeros([nstates,nstates], numpy.float64)
    for istate in range(nstates):
        Tij[istate,:] = Nij[istate,:] / Nij[istate,:].sum()

    if show_transition_matrix:
        # Print observed transition probabilities.
        PRINT_CUTOFF = 0.001 # Cutoff for displaying fraction of accepted swaps.
        print "Cumulative symmetrized state mixing transition matrix:"
        print "%6s" % "",
        for jstate in range(nstates):
            print "%6d" % jstate,
        print ""
        for istate in range(nstates):
            print "%-6d" % istate,
            for jstate in range(nstates):
                P = Tij[istate,jstate]
                if (P >= PRINT_CUTOFF):
                    print "%6.3f" % P,
                else:
                    print "%6s" % "",
            print ""

    # Estimate second eigenvalue and equilibration time.
    mu = numpy.linalg.eigvals(Tij)
    mu = -numpy.sort(-mu) # sort in descending order
    if (mu[1] >= 1):
        print "Perron eigenvalue is unity; Markov chain is decomposable."
    else:
        print "Perron eigenvalue is %9.5f; state equilibration timescale is ~ %.1f iterations" % (mu[1], 1.0 / (1.0 - mu[1]))

    return

def show_mixing_statistics_with_error(ncfile, nblocks=10, show_transition_matrix=False):
    """
    Print summary of mixing statistics.

    ARGUMENTS
      ncfile - NetCDF file handle

    OPTIONAL ARGUMENTS
      nblocks - number of blocks to divide data into (default: 10)
    
    """

    print "Computing mixing statistics..."

    states = ncfile.variables['states'][:,:].copy()

    # Determine number of iterations and states.
    [niterations, nstates] = ncfile.variables['states'][:,:].shape
    
    # Analyze subblocks.
    blocksize = int(niterations)/int(nblocks)
    mu2_i = numpy.zeros([nblocks], numpy.float64)
    tau_i = numpy.zeros([nblocks], numpy.float64)
    for block_index in range(nblocks):
        # Compute statistics of transitions.
        Nij = numpy.zeros([nstates,nstates], numpy.float64)
        for iteration in range(blocksize*block_index, blocksize*(block_index+1)-1):
            for ireplica in range(nstates):
                istate = states[iteration,ireplica]
                jstate = states[iteration+1,ireplica]
                Nij[istate,jstate] += 0.5
                Nij[jstate,istate] += 0.5
        Tij = numpy.zeros([nstates,nstates], numpy.float64)
        for istate in range(nstates):
            Tij[istate,:] = Nij[istate,:] / Nij[istate,:].sum()

        # Estimate second eigenvalue and equilibration time.
        mu = numpy.linalg.eigvals(Tij)
        mu = -numpy.sort(-mu) # sort in descending order

        # Store results.
        mu2_i[block_index] = mu[1]
        tau_i[block_index] = 1.0 / (1.0 - mu[1])
    dmu2 = mu2_i.std() / numpy.sqrt(float(nblocks))
    dtau = tau_i.std() / numpy.sqrt(float(nblocks))
    
    # Compute statistics of transitions using whole dataset.
    Nij = numpy.zeros([nstates,nstates], numpy.float64)
    for iteration in range(niterations-1):
        for ireplica in range(nstates):
            istate = states[iteration,ireplica]
            jstate = states[iteration+1,ireplica]
            Nij[istate,jstate] += 0.5
            Nij[jstate,istate] += 0.5
    Tij = numpy.zeros([nstates,nstates], numpy.float64)
    for istate in range(nstates):
        Tij[istate,:] = Nij[istate,:] / Nij[istate,:].sum()

    if show_transition_matrix:
        # Print observed transition probabilities.
        PRINT_CUTOFF = 0.001 # Cutoff for displaying fraction of accepted swaps.
        print "Cumulative symmetrized state mixing transition matrix:"
        print "%6s" % "",
        for jstate in range(nstates):
            print "%6d" % jstate,
        print ""
        for istate in range(nstates):
            print "%-6d" % istate,
            for jstate in range(nstates):
                P = Tij[istate,jstate]
                if (P >= PRINT_CUTOFF):
                    print "%6.3f" % P,
                else:
                    print "%6s" % "",
            print ""

    # Estimate second eigenvalue and equilibration time.
    mu = numpy.linalg.eigvals(Tij)
    mu = -numpy.sort(-mu) # sort in descending order

    # Compute Perron eigenvalue and timescale.
    mu2 = mu[1]
    tau = 1.0 / (1.0 - mu[1])

    if (mu[1] >= 1):
        print "Perron eigenvalue is unity; Markov chain is decomposable."
    else:
        print "Perron eigenvalue is %9.5f+-%.5f; state equilibration timescale is ~ %.3f+-%.3f iterations" % (mu2, dmu2, tau, dtau)

    return [tau, dtau]

def compute_relaxation_time(bin_it, nbins):
    """
    Compute relaxation time from empirical transition matrix of binned coordinate trajectories.

    """

    [nstates, niterations] = bin_it.shape
    
    # Compute statistics of transitions.
    Nij = numpy.zeros([nbins,nbins], numpy.float64)
    for ireplica in range(nstates):
        for iteration in range(niterations-1):        
            ibin = bin_it[ireplica, iteration]
            jbin = bin_it[ireplica, iteration+1]
            Nij[ibin,jbin] += 0.5
            Nij[jbin,ibin] += 0.5
    Ni = Nij.sum(axis=1)
    print "Ni = "
    print Ni
    Tij = numpy.zeros([nbins,nbins], numpy.float64)    
    for ibin in range(nbins):
        Tij[ibin,ibin] = 1.0        
        if Ni[ibin] > 0.0:
            Tij[ibin,:] = Nij[ibin,:] / Ni[ibin]
        
    mu = numpy.linalg.eigvals(Tij)
    mu = -numpy.sort(-mu) # sort in descending order
    print "eigenvalues of transition matrix:"
    print mu
    tau = 1.0 / (1.0 - mu[1])
    
    return tau

def average_end_to_end_time(states):
    """
    Estimate average end-to-end time.

    """

    # Determine number of iterations and states.
    [niterations, nstates] = states.shape

    events = list()
    # Look for 0 -> (nstates-1) transitions.
    for state in range(nstates):
        last_endpoint = None
        for iteration in range(niterations):
            if (states[iteration,state] in [0,nstates-1]):
                if (last_endpoint is None):
                    last_endpoint = iteration
                elif (states[last_endpoint,state] != states[iteration,state]):
                    events.append(iteration-last_endpoint)
                    last_endpoint = iteration                
    events = numpy.array(events, numpy.float64)
    print "%d end to end events" % (events.size)
    tau_end = events.mean()
    dtau_end = events.std() / numpy.sqrt(events.size)               

    return [tau_end, dtau_end]

#=============================================================================================
# MAIN AND TESTS
#=============================================================================================
    
if __name__ == "__main__":

    temperature = 300.0 * units.kelvin # temperature

    #prefixes = [ 'parallel-tempering-allswap', 'parallel-tempering-neighborswap' ]
    #prefixes = [ 'parallel-tempering-allswap-alaninedipeptide', 'parallel-tempering-neighborswap-alaninedipeptide' ] # for alanine dipeptide
    #prefixes = [ 'parallel-tempering-allswap-alaninedipeptide-2000', 'parallel-tempering-neighborswap-alaninedipeptide-2000' ] # for alanine dipeptide, 2000 iterations
    prefixes = [ 'parallel-tempering-allswap-alaninedipeptide-new', 'parallel-tempering-neighborswap-alaninedipeptide-new' ] # for alanine dipeptide

    for prefix in prefixes:
        store_filename = os.path.join('data', prefix + ".nc")
        print store_filename
        
        # Open NetCDF file.
        ncfile = netcdf.Dataset(store_filename, 'r', version=2)

        # Get dimensions.
        [niterations, nstates, natoms, ndim] = ncfile.variables['positions'][:,:,:,:].shape    
        print "%d iterations, %d states, %d atoms" % (niterations, nstates, natoms)
    
        # Print summary statistics about mixing in state space.
        [tau2, dtau2] = show_mixing_statistics_with_error(ncfile)
                
        # Write replica data.
        #states = ncfile.variables['states'][:,:].copy()
        #filename = prefix + '.replica_states'
        #outfile = open(filename, 'w')
        #for iteration in range(niterations):
        #    for replica in range(nstates):
        #        outfile.write('%5d' % states[iteration,replica])
        #    outfile.write('\n')                       
        #outfile.close()
        #del states

        # Compute correlation time of state index.
        states = ncfile.variables['states'][:,:].copy()
        A_kn = [ states[:,k].copy() for k in range(nstates) ]
        g_states = timeseries.statisticalInefficiencyMultiple(A_kn)
        tau_states = (g_states-1.0)/2.0
        # Compute statistical error.
        nblocks = 10
        blocksize = int(niterations) / int(nblocks)
        g_states_i = numpy.zeros([nblocks], numpy.float64)
        tau_states_i = numpy.zeros([nblocks], numpy.float64)        
        for block_index in range(nblocks):
            # Extract block
            states = ncfile.variables['states'][(blocksize*block_index):(blocksize*(block_index+1)),:].copy()
            A_kn = [ states[:,k].copy() for k in range(nstates) ]
            g_states_i[block_index] = timeseries.statisticalInefficiencyMultiple(A_kn)
            tau_states_i[block_index] = (g_states_i[block_index]-1.0)/2.0            
        dg_states = g_states_i.std() / numpy.sqrt(float(nblocks))
        dtau_states = tau_states_i.std() / numpy.sqrt(float(nblocks))
        # Print.
        print "g_states = %.3f+-%.3f iterations" % (g_states, dg_states)
        print "tau_states = %.3f+-%.3f iterations" % (tau_states, dtau_states)
        del states, A_kn

        # Compute end-to-end time.
        states = ncfile.variables['states'][:,:].copy()
        [tau_end, dtau_end] = average_end_to_end_time(states)
#        # Compute statistical error.
#        nblocks = 10
#        blocksize = int(niterations) / int(nblocks)
#        tau_end_i = numpy.zeros([nblocks], numpy.float64)        
#        for block_index in range(nblocks):
#            # Extract block
#            states = ncfile.variables['states'][(blocksize*block_index):(blocksize*(block_index+1)),:].copy()
#            tau_end_i[block_index] = average_end_to_end_time(states)            
#        dtau_end = tau_end_i.std() / numpy.sqrt(float(nblocks))
        # Print.
        print "tau_end = %.3f+-%.3f iterations" % (tau_end, dtau_end)
        del states

        # Compute statistical inefficiency for reduced potential
        energies = ncfile.variables['energies'][:,:,:].copy()
        states = ncfile.variables['states'][:,:].copy()    
        u_n = numpy.zeros([niterations], numpy.float64)
        for iteration in range(niterations):
            u_n[iteration] = 0.0
            for replica in range(nstates):
                state = states[iteration,replica]
                u_n[iteration] += energies[iteration,replica,state]
        del energies, states
        g_u = timeseries.statisticalInefficiency(u_n)
        tau_u = (g_u-1.0)/2.0
        print "g_u = %8.1f iterations" % g_u
        print "tau_u = %8.1f iterations" % tau_u

        # DEBUG for lactalbumin
        #continue

        # Compute torsions.
        print "Computing torsions..."
        positions = ncfile.variables['positions'][:,:,:,:]
        coordinates = units.Quantity(numpy.zeros([natoms,ndim], numpy.float32), units.angstroms)
        phi_it = units.Quantity(numpy.zeros([nstates,niterations], numpy.float32), units.radians)
        psi_it = units.Quantity(numpy.zeros([nstates,niterations], numpy.float32), units.radians)
        for iteration in range(niterations):
            for replica in range(nstates):
                coordinates[:,:] = units.Quantity(positions[iteration,replica,:,:].copy(), units.angstroms)
                phi_it[replica,iteration] = compute_torsion(coordinates, 4, 6, 8, 14) 
                psi_it[replica,iteration] = compute_torsion(coordinates, 6, 8, 14, 16)

        # Compute statistical inefficiencies of various functions of the timeseries data.
        print "Computing statistical infficiencies of cos(phi), sin(phi), cos(psi), sin(psi)..."
        cosphi_kn = [ numpy.cos(phi_it[replica,:] / units.radians).copy() for replica in range(1,nstates) ]
        sinphi_kn = [ numpy.sin(phi_it[replica,:] / units.radians).copy() for replica in range(1,nstates) ]
        cospsi_kn = [ numpy.cos(psi_it[replica,:] / units.radians).copy() for replica in range(1,nstates) ]
        sinpsi_kn = [ numpy.sin(psi_it[replica,:] / units.radians).copy() for replica in range(1,nstates) ]
        g_cosphi = timeseries.statisticalInefficiencyMultiple(cosphi_kn)
        g_sinphi = timeseries.statisticalInefficiencyMultiple(sinphi_kn)
        g_cospsi = timeseries.statisticalInefficiencyMultiple(cospsi_kn)
        g_sinpsi = timeseries.statisticalInefficiencyMultiple(sinpsi_kn)
        tau_cosphi = (g_cosphi-1.0)/2.0
        tau_sinphi = (g_sinphi-1.0)/2.0
        tau_cospsi = (g_cospsi-1.0)/2.0
        tau_sinpsi = (g_sinpsi-1.0)/2.0
        
        # Compute statistical error.
        nblocks = 10
        blocksize = int(niterations) / int(nblocks)
        g_cosphi_i = numpy.zeros([nblocks], numpy.float64)
        g_sinphi_i = numpy.zeros([nblocks], numpy.float64)
        g_cospsi_i = numpy.zeros([nblocks], numpy.float64)
        g_sinpsi_i = numpy.zeros([nblocks], numpy.float64)        
        tau_cosphi_i = numpy.zeros([nblocks], numpy.float64)
        tau_sinphi_i = numpy.zeros([nblocks], numpy.float64)
        tau_cospsi_i = numpy.zeros([nblocks], numpy.float64)
        tau_sinpsi_i = numpy.zeros([nblocks], numpy.float64)                
        for block_index in range(nblocks):
            # Extract block  
            slice_indices = range(blocksize*block_index,blocksize*(block_index+1))
            cosphi_kn = [ numpy.cos(phi_it[replica,slice_indices] / units.radians).copy() for replica in range(1,nstates) ]
            sinphi_kn = [ numpy.sin(phi_it[replica,slice_indices] / units.radians).copy() for replica in range(1,nstates) ]
            cospsi_kn = [ numpy.cos(psi_it[replica,slice_indices] / units.radians).copy() for replica in range(1,nstates) ]
            sinpsi_kn = [ numpy.sin(psi_it[replica,slice_indices] / units.radians).copy() for replica in range(1,nstates) ]
            g_cosphi_i[block_index] = timeseries.statisticalInefficiencyMultiple(cosphi_kn)
            g_sinphi_i[block_index] = timeseries.statisticalInefficiencyMultiple(sinphi_kn)
            g_cospsi_i[block_index] = timeseries.statisticalInefficiencyMultiple(cospsi_kn)
            g_sinpsi_i[block_index] = timeseries.statisticalInefficiencyMultiple(sinpsi_kn)
            tau_cosphi_i[block_index] = (g_cosphi_i[block_index]-1.0)/2.0
            tau_sinphi_i[block_index] = (g_sinphi_i[block_index]-1.0)/2.0
            tau_cospsi_i[block_index] = (g_cospsi_i[block_index]-1.0)/2.0
            tau_sinpsi_i[block_index] = (g_sinpsi_i[block_index]-1.0)/2.0

        dtau_cosphi = tau_cosphi_i.std() / numpy.sqrt(float(nblocks))
        dtau_sinphi = tau_sinphi_i.std() / numpy.sqrt(float(nblocks))
        dtau_cospsi = tau_cospsi_i.std() / numpy.sqrt(float(nblocks))
        dtau_sinpsi = tau_sinpsi_i.std() / numpy.sqrt(float(nblocks))        

        del cosphi_kn, sinphi_kn, cospsi_kn, sinpsi_kn

        print "Integrated autocorrelation times"
        print "tau_cosphi = %8.1f+-%.1f iterations" % (tau_cosphi, dtau_cosphi)
        print "tau_sinphi = %8.1f+-%.1f iterations" % (tau_sinphi, dtau_sinphi)
        print "tau_cospsi = %8.1f+-%.1f iterations" % (tau_cospsi, dtau_cospsi)
        print "tau_sinpsi = %8.1f+-%.1f iterations" % (tau_sinpsi, dtau_sinpsi)

        # Compute relaxation times in each torsion.
        print "Relaxation times for transitions among phi or psi bins alone:"
        nbins = 50 # number of bins per torsion
        delta = 360.0 / (nbins - 0.01)
        phibin_it = ((phi_it / units.degrees + 180.0) / delta).astype(numpy.int16)
        tau_phi = compute_relaxation_time(phibin_it, nbins)
        psibin_it = ((psi_it / units.degrees + 180.0) / delta).astype(numpy.int16)
        tau_psi = compute_relaxation_time(psibin_it, nbins)
        print "tau_phi = %8.1f iteration" % tau_phi
        print "tau_psi = %8.1f iteration" % tau_psi
        
        # Done.
        print ""

        # Print LaTeX line.
        print "%(prefix)s & %(tau2).2f $\pm$ %(dtau2).2f & %(tau_states).2f $\pm$ %(dtau_states).2f & %(tau_end).2f $\pm$ %(dtau_end).2f & %(tau_cosphi).2f $\pm$ %(dtau_cosphi).2f & %(tau_sinphi).2f $\pm$ %(dtau_sinphi).2f & %(tau_cospsi).2f $\pm$ %(dtau_cospsi).2f & %(tau_sinpsi).2f $\pm$ %(dtau_sinpsi).2f \\\\" % vars()
        
