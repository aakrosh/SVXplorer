#!/usr/bin/env python

# Pick variants having minimum unique support for each support category (SR, PE, MIXED)

import sys
import math
from collections import Counter
import argparse
import logging

def readBamStats(statFile):
    f=open(statFile,"r")
    for i,line in enumerate(f):
        if i==3:
            break
    return float(line.split()[0])

def formMQSet(mapThresh, mqSet, allDiscordantsFile):
    f=open(allDiscordantsFile,"r")
    for line in f:
        line_split = line.split()
        frag = int(line_split[0])
        mq = int(line_split[7])
        # mapping qual threshold for uniquely supporting fragments
        if frag not in mqSet and mq >= mapThresh:
            mqSet.add(frag)
    f.close()

def calculateSVThresh(SVType, SVSupp, complex_thresh, sr_thresh, pe_thresh, 
                      mix_thresh, NPEClusters, pe_min):
    #pe-based unknown events listed here; last INV will be listed as BND unless SR-supported as INV_B (thus supp will be > 3)
    if SVType == "Unknown" or SVType.startswith("INS_half") or SVType == "BND" or \
        SVType == "DN_INS_NM" or (SVType.startswith("INV") and NPEClusters == 1):
        #set bnd_thresh = complex_thresh
        disjThresh = complex_thresh
    elif SVType.startswith("INV") or SVType.startswith("DN_INS") or SVType.startswith("INS"):
        disjThresh = complex_thresh
    elif SVSupp.find("PE") == -1 and SVSupp.find("SR") != -1:
        disjThresh = sr_thresh
    elif SVSupp.find("PE") != -1 and SVSupp.find("SR") == -1:
        disjThresh = pe_thresh
    elif SVSupp.find("PE") != -1 and SVSupp.find("SR") != -1:
        disjThresh = mix_thresh
    return disjThresh

def uniquenessFilter(fragmentList, nInputVariants, mqSet, allDiscordantsFile,
                     mapThresh,variantMapFile, allVariantFile, 
                     rdFragIndex, workDir, complex_thresh, 
                     sr_thresh, pe_thresh, mix_thresh, pe_min):

    nSVs = 0
    disjointness = [0]*nInputVariants
    pickV = [0]*nInputVariants
    varNum = []
    fVM=open(variantMapFile,"r")
    fAV=open(allVariantFile,"r")
    fUF=open(workDir+"/variants.uniqueFilter.txt","w")
    formMQSet(mapThresh, mqSet, allDiscordantsFile)
    header = fAV.readline()
    logging.info("Applying uniqueness filter.")
    nFragOccrns = Counter(fragmentList)
    # obtain disjointness count
    # assumed any given fragment only appears once in set list
    for counter, line in enumerate(fVM):
        currentSet = map(int, line.split())
        varNum.append(currentSet[0])
        currentSet = currentSet[1:]
        disjThresh = -1

        for line in fAV:
            SVType = line.split()[1]
            SVSupp = line.split()[11]
            NPEClusters = int(line.split()[12])
            disjThresh = calculateSVThresh(SVType, SVSupp, complex_thresh, 
                                           sr_thresh, pe_thresh, mix_thresh, NPEClusters, pe_min)
            break

        for elem in currentSet:
            #pick those supported by RD automatically
            if elem >= rdFragIndex:
                if nFragOccrns[elem] == 1:
                    disjointness[counter]+=1
                pickV[counter] = 2
                #$why didn't write variant here and avoid next fAV loop?
            #if SR, no secondaries so is above MQ_THRESH automatically
            elif nFragOccrns[elem] == 1 and (elem in mqSet or elem < 0):
                disjointness[counter]+=1
            if disjointness[counter] == disjThresh:
                break
    fAV.seek(0)
    header = fAV.readline()
    for g,item in enumerate(disjointness):
        for line in fAV:
            SVType = line.split()[1]
            SVSupp = line.split()[11]
            NPEClusters = int(line.split()[12])
            disjThresh = calculateSVThresh(SVType, SVSupp, complex_thresh,
                                           sr_thresh, pe_thresh, mix_thresh, NPEClusters, pe_min)
            break

        if (item >= disjThresh) or (item >= 1 and pickV[g] == 2):
            fUF.write("%s\n" %varNum[g])
            nSVs+=1

    fVM.close()
    fAV.close()
    fUF.close()
    return nSVs

def readVariantMap(filename, allFrags):
    f=open(filename, 'r')
    index = 0
    for counter, line in enumerate(f):
        parsed = map(int, line.split())
        for frag in parsed[1:]:
            allFrags.append(frag)
        index = counter
    f.close()
    return index + 1

def uniqueSuppFilter(workDir, statFile, variantMapFile, allVariantFile, 
                     allDiscordantsFile, map_thresh,
                     pe_thresh_max, sr_thresh_max, 
                     pe_thresh_min, sr_thresh_min,
                     rdFragIndex, unfilter):
    allFrags = []
    mqSet = set()

    # linear model to calculate support threshold by category
    # familiar developers may tweak model here directly
    pe_low = 3
    pe_high = 5
    covg_low = 5
    covg_high = 50
    sr_low = 3
    sr_high = 5
    il_low1 = 25
    il_low2 = 35
    covg_cusp = 8
    # apply above-mentioned support threshold model
    covg = readBamStats(statFile)
    if covg <= covg_cusp or unfilter:
        complex_thresh, mix_thresh = 3, 3
    else:
        complex_thresh, mix_thresh = 4, 4

    if not unfilter:
        sr_thresh = math.floor(sr_low + (covg-covg_low)*1.0*(sr_high - sr_low)/(covg_high - covg_low))
        pe_thresh = round(pe_low + (covg-covg_low)*1.0*(pe_high - pe_low)/(covg_high - covg_low))
    else:
        sr_thresh, pe_thresh = 3,3

    if pe_thresh > pe_thresh_max:
        pe_thresh = pe_thresh_max
    if sr_thresh > sr_thresh_max:
        sr_thresh = sr_thresh_max
    if pe_thresh < pe_thresh_min:
        pe_thresh = pe_thresh_min
    if sr_thresh < sr_thresh_min:
        sr_thresh = sr_thresh_min
    logging.info("sr, pe threshes, covg are: %d, %d, %d", sr_thresh, pe_thresh, covg)

    nInputVariants = readVariantMap(variantMapFile, allFrags)
    nSVs = uniquenessFilter(allFrags, nInputVariants, mqSet, allDiscordantsFile, 
                            map_thresh, variantMapFile, allVariantFile,
                            rdFragIndex, workDir, complex_thresh, 
                            sr_thresh, pe_thresh, mix_thresh, pe_low)
    fNSVs= open(workDir+"/NSVs.txt","w")
    fNSVs.write("%s\n" %nSVs)
    fNSVs.close()

if __name__ == "__main__":
    PARSER = argparse.ArgumentParser(description='Apply uniquenes Filter: pick variants having minimum unique support for each support category (SR, PE, MIXED)', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    PARSER.add_argument('workDir', help='Work directory')
    PARSER.add_argument('statFile', help='File containing BAM statistics, typically bamStats.txt')
    PARSER.add_argument('variantMapFile', help='File containing variant map, typically variantMap._.txt')
    PARSER.add_argument('allVariantFile', help='File containing list of variants, typically allVariants._.txt')
    PARSER.add_argument('allDiscordantsFile', help='File containing all discordants with MQ,typically allDiscordants.txt')
    PARSER.add_argument('-a', default=6, dest='pe_thresh_max', type=int,
        help='Maximum allowed support threshold for PE-only variants (dynamic)')
    PARSER.add_argument('-b', default=6, dest='sr_thresh_max', type=int,
        help='Maximum allowed support threshold for SR-only variants')
    PARSER.add_argument('-c', default=3, dest='pe_thresh_min', type=int,
        help='Minimum allowed support threshold for PE-only variants')
    PARSER.add_argument('-d', action='store_true', dest='debug', help='print debug information')
    PARSER.add_argument('-m', default=3, dest='sr_thresh_min', type=int,
        help='Minimum allowed support threshold for SR-only variants')
    PARSER.add_argument('-g', default=10, dest='map_thresh', type=int,
        help='Mapping quality threshold for fragments uniquely supporting variant')
    PARSER.add_argument('-i', default=100000000, dest='rdFragIndex', type=int,
        help=argparse.SUPPRESS)
    ARGS = PARSER.parse_args()

    LEVEL = logging.INFO
    if ARGS.debug:
        LEVEL = logging.DEBUG

    logging.basicConfig(level=LEVEL,
                        format='%(asctime)s %(levelname)s %(message)s',
                        datefmt='%m/%d/%Y %I:%M:%S %p')

    uniqueSuppFilter(ARGS.workDir, ARGS.statFile, ARGS.variantMapFile, 
                     ARGS.allVariantFile, ARGS.allDiscordantsFile,
                     ARGS.map_thresh, ARGS.pe_thresh_max,
                     ARGS.sr_thresh_max, ARGS.pe_thresh_min,
                     ARGS.sr_thresh_min,
                     ARGS.rdFragIndex, False)

    logging.shutdown()
