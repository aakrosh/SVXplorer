#!/usr/bin/env python

# Add Split Reads to support existing PE variants and create new SR variants

import pysam
import sys
import argparse
import logging

from shared import formExcludeHash, ignoreRead, readChromosomeLengths

class newSRVar(object):
    def __init__(self):
        self.l_orient = -1
        self.r_orient = -1
        self.swapped = -1
        self.bp2 = -1
        self.bp3 = -1
        self.count = 1
        self.support = []
        self.bp3tid = -1
        self.typeSV = -1
        self.tag = -1
        self.neighbor_tags = []
        self.hash_pair_tag = -1
        self.n_changes = 0
        self.write = -1
        self.isOriginal = -1
        self.insToInv = -1
    def __str__(self):
       return "%s\t%s\t%s\t%s\t%s" %(self.bp2, self.bp3, self.count, self.isOriginal, self.typeSV)

class SRAlmt(object):
    def __init__(self):
        self.bp = -1
        self.tid = -1
        self.tid_2 = -1
    def __str__(self):
        return "%s\t%s\t%s" %(self.bp, self.tid, self.tid_2)
    def __hash__(self):
        return hash((self.bp, self.tid, self.tid_2))
    def __eq__(self, other):
        return (self.bp, self.tid, self.tid_2) == (other.bp, other.tid, other.tid_2)
    def __ne__(self, other):
        # not strictly necessary
        return not(self == other)

class PEVarDetails(object):
    def __init__(self):
        self.bp2_1 = -1
        self.bp2_2 = -1
        self.bp3_1 = -1
        self.bp3_2 = -1
        self.typeSV = -1
        self.num = -1

    def __str__(self):
        return "%s\t%s\t%s\t%s\t%s\t%s" %(self.bp2_1, self.bp2_2, self.bp3_1, self.bp3_2, self.typeSV, self.num)

def transferSupport(variant1, variant2):
    # 1st fragment is shared
    for elem in variant2.support[1:]:
        variant1.support.append(elem)
        variant1.count+=1

def mapSVtoNum(SV_type):
    if SV_type== "DEL":
        return 0
    elif SV_type == "TD":
        return 1
    elif SV_type == "INV":
        return 2
    elif SV_type == "INS":
        return 3
    elif SV_type == "INS_I":
        return 4
    else:
        return -1

def formPEHash(fAV, iObjects, SVHashPE, slop):
    logging.info('Started reading the PE variants')
    for line in fAV:
        line_s = line.split()
        SV_specsPE = PEVarDetails()
        SV_specsPE.num = int(line_s[0])
        SV_specsPE.typeSV= mapSVtoNum(line_s[1])
        if SV_specsPE.typeSV == -1:
            continue
        if SV_specsPE.typeSV == 3 or SV_specsPE.typeSV == 4:
            SV_specsPE.bp3_1 = int(line_s[9]) - slop
            SV_specsPE.bp3_2 = int(line_s[10]) + slop
        SV_specsPE.bp2_1 = int(line_s[6]) - slop
        SV_specsPE.bp2_2 = int(line_s[7]) + slop

        # hash all values within bp margin
        for x in range(int(line_s[3])-int(slop), int(line_s[4]) + int(slop)):
            almt = SRAlmt()
            almt.tid = line_s[2]
            if line_s[5] != almt.tid:
                almt.tid_2 = line_s[5]
            almt.bp = x
            #immutable hash objects -- preserve so memory doesn't get overwritten
            iObjects.append(almt)
            if almt not in SVHashPE:
                SVHashPE[almt] = SV_specsPE
    logging.info('Finished reading the PE variants')
    return SV_specsPE.num

def addSplitReads(workDir, variantMapFilePE, allVariantFilePE, bamFileSR,
                  slop, refRate, min_vs, mapThresh, ignoreChr, minSizeINS,
                  minSRtoPEsupport, ignoreBED):
    fAV = open(workDir+"/allVariants.pe.txt","r")
    fVM = open(workDir+"/variantMap.pe.txt","r")
    fAVN = open(workDir+"/allVariants.pe_sr.txt","w")
    fVMN = open(workDir+"/variantMap.pe_sr.txt","w")
    riskINV = True
    SVHashPE = {}
    SRVarHash = {}
    # preserve list of complex hash objects
    immutable_objects = []

    # save the PE variants
    nSVsPE = formPEHash(fAV, immutable_objects, SVHashPE, slop)

    SRFrag = 0
    SRtoPESuppFrags = [[] for _ in range(1+nSVsPE)]
    SRtoPESuppList = {}
    newSRList = []
    bamfile = pysam.Samfile(bamFileSR,"rb")
    # if subsampling: shouldn't be required`
    bp1Prev = -1
    bp1TID = -1
    bp2Prev = -1
    bp2TID = -1

    ignoreList = set()
    if ignoreChr is not None:
        with open(ignoreChr, "r") as fIC:
            for line in fIC:
                ignoreList.add(line.strip().split()[0])

    chromosome_lengths = readChromosomeLengths(bamFileSR)

    chrHash = {}
    if ignoreBED is not None:
        logging.info("Regions in %s will be ignored", ignoreBED)
        formExcludeHash(chrHash, 0, ignoreBED, chromosome_lengths)

    # all split reads should be mapped, unique alignments
    while True:
        try:
            sr1 = bamfile.next()
            sr2 = bamfile.next()
        except StopIteration:
            break
        varType = -1
        if sr1.qname == sr2.qname:
            #print sr1, sr2
            SRFrag-=1
            sr_bp1 = sr1.reference_start
            sr_bp2 = sr2.reference_start
            sr_bp1_tid = sr1.reference_name
            sr_bp2_tid = sr2.reference_name

            # ignore marked chromosomes
            if sr1.reference_name in ignoreList or \
               sr2.reference_name in ignoreList or \
               sr1.mapping_quality < mapThresh or \
               sr2.mapping_quality < mapThresh or \
               ignoreRead(sr_bp1_tid, sr_bp1, sr_bp2_tid, sr_bp2, chrHash) or \
               (sr_bp1_tid == bp1TID and sr_bp2_tid == bp2TID and abs(sr_bp1 - bp1Prev) < refRate and abs(sr_bp2 - bp2Prev) < refRate):
                    continue

            bp1Prev = sr_bp1
            bp1TID = sr_bp1_tid
            bp2Prev = sr_bp2
            bp2TID = sr_bp2_tid

            ## SET SWAP AND RISK
            if sr_bp1 < sr_bp2:
                minsr = sr1
                maxsr = sr2
            else:
                maxsr = sr1
                minsr = sr2
            sr_bp1_tid = minsr.reference_name
            sr_bp2_tid = maxsr.reference_name
            # QAS below refers to the alignment position of split read relative to whole read
            # swap value accurate for 75% of inversion reads but even if incorrect, used benignly
            if sr_bp1_tid == sr_bp2_tid and minsr.query_alignment_start > maxsr.query_alignment_start:
                swap = 1
                if minsr.is_reverse == maxsr.is_reverse:
                    # unless both reads are inverted and swapped -- less likely
                    sr_bp1 = minsr.reference_start
                    sr_bp2 = maxsr.reference_end
                # "risk" not catching some inverted copy-paste insertions but these are few
                elif riskINV:
                    sr_bp1 = minsr.reference_end
                    sr_bp2 = maxsr.reference_end
            # note: query start positions (QAS) of both reads can be 0, which happens in 50% of SRs from INVs
            else:
                swap = 0
                if minsr.is_reverse == maxsr.is_reverse:
                    sr_bp1 = minsr.reference_end
                    sr_bp2 = maxsr.reference_start
                elif riskINV:
                    if minsr.is_reverse:
                        sr_bp1 = minsr.reference_start
                        sr_bp2 = maxsr.reference_start
                    else:
                        sr_bp1 = minsr.reference_end
                        sr_bp2 = maxsr.reference_end
        else:
            sys.stderr.write("Please check if split-read file is name-sorted.")
            exit(1)

        ## CHECK CURRENT SR ALMT AGAINST EXISTING PE VARIANTS FOR MATCH
        match = 0
        newAlmt = SRAlmt()
        newAlmt.bp = sr_bp1
        newAlmt.tid = sr_bp1_tid
        if sr_bp1_tid != sr_bp2_tid:
            newAlmt.tid_2 = sr_bp2_tid
        if newAlmt in SVHashPE and (SVHashPE[newAlmt].bp2_1 < sr_bp2 < SVHashPE[newAlmt].bp2_2 or \
            SVHashPE[newAlmt].bp3_1 < sr_bp2 < SVHashPE[newAlmt].bp3_2):

            varNumPE = SVHashPE[newAlmt].num
            varType = SVHashPE[newAlmt].typeSV
            if varNumPE not in SRtoPESuppList:
                newBp = [sr_bp1, sr_bp2, -1]
        # if not found, try other side of SR
        else:
            newAlmt = SRAlmt()
            newAlmt.bp = sr_bp2
            newAlmt.tid = sr_bp2_tid
            newAlmt.tid_2 = -1
            if sr_bp1_tid != sr_bp2_tid:
                newAlmt.tid_2 = sr_bp1_tid
            if newAlmt in SVHashPE and (SVHashPE[newAlmt].bp2_1 < sr_bp1 < SVHashPE[newAlmt].bp2_2 \
                or SVHashPE[newAlmt].bp3_1 < sr_bp1 < SVHashPE[newAlmt].bp3_2):

                varNumPE = SVHashPE[newAlmt].num
                varType = SVHashPE[newAlmt].typeSV
                if varNumPE not in SRtoPESuppList:
                    newBp = [sr_bp2, sr_bp1, -1]
        #check DEL
        if varType == 0 and swap==0 and minsr.is_reverse == maxsr.is_reverse:
            match = 1
        #check TD
        elif varType == 1 and swap==1 and minsr.is_reverse == maxsr.is_reverse:
            match = 1
        #check INV
        elif varType == 2 and swap==0 and minsr.is_reverse != maxsr.is_reverse:
            match = 1
        #check INS
        elif (varType == 3 and minsr.is_reverse == maxsr.is_reverse) or \
            (varType == 4 and minsr.is_reverse != maxsr.is_reverse):
            match = 1
            # Set new bp3 of insertion if unset
            if varNumPE in SRtoPESuppList and SRtoPESuppList[varNumPE][2] == -1:
                SRtoPESupp_bp = SRtoPESuppList[varNumPE]
                if abs(sr_bp1 - SRtoPESupp_bp[0]) > 2*slop and abs(sr_bp1 - SRtoPESupp_bp[1]) > 2*slop \
                    and SVHashPE[newAlmt].bp3_1 < sr_bp1 < SVHashPE[newAlmt].bp3_2:
                    SRtoPESuppList[varNumPE][2] = sr_bp1
                elif abs(sr_bp2 - SRtoPESupp_bp[0]) > 2*slop and abs(sr_bp2 - SRtoPESupp_bp[1]) > 2*slop and \
                    SVHashPE[newAlmt].bp3_1 < sr_bp2 < SVHashPE[newAlmt].bp3_2:
                    SRtoPESuppList[varNumPE][2] = sr_bp2
                # insertion bp2 should be < bp3
                if SRtoPESuppList[varNumPE][2] != -1 and SRtoPESuppList[varNumPE][2] < SRtoPESuppList[varNumPE][1]:
                    SRtoPESuppList[varNumPE][2], SRtoPESuppList[varNumPE][1] =\
                        SRtoPESuppList[varNumPE][2], SRtoPESuppList[varNumPE][1]
        # if matches existing PE SV
        if match:
            if varNumPE not in SRtoPESuppList:
                SRtoPESuppList[varNumPE] = newBp
                SRtoPESuppFrags[varNumPE].append(SRFrag)
            else:
                SRtoPESuppFrags[varNumPE].append(SRFrag)
        # if SR fragment did not match existing PE variant, check existing SR variant list
        else:
            almtMatchesSVbps = 0
            almtSupportsSV = 0
            newAlmt = SRAlmt()
            newAlmt.bp = sr_bp1
            newAlmt.tid = sr_bp1_tid
            # bp1 is left bp, bp2 is right bp if same chr
            newAlmt.tid_2 = sr_bp2_tid
            l_orient = minsr.is_reverse
            r_orient = maxsr.is_reverse

            if newAlmt in SRVarHash:
                almtMatchesSVbps = 1
                other_bp = sr_bp2
                other_bp_tid = sr_bp2_tid
            else:
                # hashing -- safe to declare new object
                newAlmt = SRAlmt()
                newAlmt.bp = sr_bp2
                newAlmt.tid = sr_bp2_tid
                newAlmt.tid_2 = sr_bp1_tid
                if newAlmt in SRVarHash:
                    almtMatchesSVbps = 1
                    other_bp = sr_bp1
                    other_bp_tid = sr_bp1_tid

            ## IF FRAGMENT SUPPORTS EXISTING SR VARIANT
            if almtMatchesSVbps:
                # do not look for inverted insertions due to ambiguity of swap parameter
                if SRVarHash[newAlmt].typeSV == "DEL_INS" or SRVarHash[newAlmt].typeSV == "DEL":
                    if l_orient == r_orient and swap==1 and not (SRVarHash[newAlmt].bp2-slop/2 <= other_bp \
                        <= SRVarHash[newAlmt].bp2+slop/2) and not ( (l_orient != SRVarHash[newAlmt].l_orient \
                        and SRVarHash[newAlmt].r_orient == r_orient) or (l_orient == SRVarHash[newAlmt].l_orient \
                        and SRVarHash[newAlmt].r_orient != r_orient) ):

                        SRVarHash[newAlmt].typeSV = "INS"
                        SRVarHash[newAlmt].bp3 = other_bp
                        SRVarHash[newAlmt].bp3tid = other_bp_tid
                        SRVarHash[newAlmt].count+=1
                        SRVarHash[newAlmt].support.append(SRFrag)
                        SRVarHash[newAlmt].n_changes+=1
                        almtSupportsSV = 1
                        #print "DEL_INS"
                    # cannot update type based on this info
                    elif swap==0 and SRVarHash[newAlmt].bp2-slop/2 <= other_bp <= SRVarHash[newAlmt].bp2+slop/2 \
                        and l_orient == r_orient == SRVarHash[newAlmt].l_orient:
                        SRVarHash[newAlmt].count+=1
                        SRVarHash[newAlmt].support.append(SRFrag)
                    elif swap==0 and SRVarHash[newAlmt].bp2-slop/2 <= other_bp <= SRVarHash[newAlmt].bp2+slop/2 \
                        and l_orient == r_orient and l_orient != SRVarHash[newAlmt].l_orient:
                        SRVarHash[newAlmt].count+=1
                        SRVarHash[newAlmt].support.append(SRFrag)
                    #TD_I
                    elif SRVarHash[newAlmt].typeSV == "TD_I":
                    #cannot update type here
                        if swap==1 and l_orient == r_orient and SRVarHash[newAlmt].bp2-slop/2 <= other_bp \
                            <= SRVarHash[newAlmt].bp2+slop/2:
                            SRVarHash[newAlmt].count+=1
                            SRVarHash[newAlmt].support.append(SRFrag)
                            #print "TD 1", SRVarHash[newAlmt].count

                    elif l_orient == r_orient and swap==0 and not (SRVarHash[newAlmt].bp2-slop/2 <= other_bp \
                            <= SRVarHash[newAlmt].bp2+slop/2 or SRVarHash[newAlmt].bp2 < newAlmt.bp < other_bp or \
                            other_bp < newAlmt.bp < SRVarHash[newAlmt].bp2) and not ( (l_orient != SRVarHash[newAlmt].l_orient \
                            and SRVarHash[newAlmt].r_orient == r_orient) or (l_orient == SRVarHash[newAlmt].l_orient \
                            and SRVarHash[newAlmt].r_orient != r_orient) ):

                        SRVarHash[newAlmt].count+=1
                        SRVarHash[newAlmt].support.append(SRFrag)
                        SRVarHash[newAlmt].typeSV = "INS"
                        SRVarHash[newAlmt].bp3 = other_bp
                        SRVarHash[newAlmt].bp3tid = other_bp_tid
                        SRVarHash[newAlmt].n_changes+=1
                    elif SRVarHash[newAlmt].typeSV[:3] == "INV" and l_orient != r_orient:
                        #cannot update type if INV_POSS currently, as only one half of inversion reported thus far
                        if SRVarHash[newAlmt].bp2-slop/2 <= other_bp <= SRVarHash[newAlmt].bp2+slop/2 and \
                            l_orient == SRVarHash[newAlmt].l_orient:
                            SRVarHash[newAlmt].count+=1
                            SRVarHash[newAlmt].support.append(SRFrag)
                        elif SRVarHash[newAlmt].bp2-slop/2 <= other_bp <= SRVarHash[newAlmt].bp2+slop/2 and \
                            l_orient != SRVarHash[newAlmt].l_orient:
                            # minor gamble -- inversions more likely than inverted insertions
                            if SRVarHash[newAlmt].typeSV == "INV_POSS":
                                SRVarHash[newAlmt].typeSV = "INV"
                                SRVarHash[newAlmt].n_changes+=1
                            SRVarHash[newAlmt].count+=1
                            SRVarHash[newAlmt].support.append(SRFrag)
                        elif not (SRVarHash[newAlmt].bp2-slop/2 <= other_bp <= SRVarHash[newAlmt].bp2+slop/2 or \
                            SRVarHash[newAlmt].bp2 < newAlmt.bp < other_bp or other_bp < newAlmt.bp < SRVarHash[newAlmt].bp2) \
                            and not ((l_orient != SRVarHash[newAlmt].l_orient and SRVarHash[newAlmt].r_orient == r_orient) \
                            or (l_orient == SRVarHash[newAlmt].l_orient and SRVarHash[newAlmt].r_orient != r_orient)):

                            SRVarHash[newAlmt].typeSV = "INS_I"
                            SRVarHash[newAlmt].count+=1
                            SRVarHash[newAlmt].support.append(SRFrag)
                            SRVarHash[newAlmt].bp3 = other_bp
                            SRVarHash[newAlmt].bp3tid = other_bp_tid
                            SRVarHash[newAlmt].n_changes+=1
                            #print "INV INS"
                elif SRVarHash[newAlmt].typeSV == "INS":
                    #print "INS"
                    if l_orient == r_orient and (SRVarHash[newAlmt].bp3 == -1 or SRVarHash[newAlmt].bp2-slop/2 \
                        <= other_bp <= SRVarHash[newAlmt].bp2+slop/2 or SRVarHash[newAlmt].bp3-slop/2 \
                        <= other_bp <= SRVarHash[newAlmt].bp3+slop/2):

                        SRVarHash[newAlmt].count+=1
                        SRVarHash[newAlmt].support.append(SRFrag)
                        if SRVarHash[newAlmt].bp3 == -1 and not (SRVarHash[newAlmt].bp2-slop/2 <= other_bp \
                            <= SRVarHash[newAlmt].bp2+slop/2 or SRVarHash[newAlmt].bp2 < newAlmt.bp < other_bp \
                            or other_bp < newAlmt.bp < SRVarHash[newAlmt].bp2):

                            SRVarHash[newAlmt].bp3 = other_bp
                            SRVarHash[newAlmt].bp3tid = other_bp_tid
                            SRVarHash[newAlmt].n_changes+=1
                #$ if 3rd bp absent write as inversion
                elif SRVarHash[newAlmt].typeSV == "INS_I":
                    #print "INS_I"
                    if l_orient != r_orient and (SRVarHash[newAlmt].bp2-slop/2 <= other_bp \
                        <= SRVarHash[newAlmt].bp2+slop/2 or SRVarHash[newAlmt].bp3 == -1 or \
                        SRVarHash[newAlmt].bp3-slop/2 <= other_bp <= SRVarHash[newAlmt].bp3+slop/2):
                        SRVarHash[newAlmt].count+=1
                        SRVarHash[newAlmt].support.append(SRFrag)

                        if SRVarHash[newAlmt].bp3 == -1 and not (SRVarHash[newAlmt].bp2-slop/2 <= other_bp \
                            <= SRVarHash[newAlmt].bp2+slop/2 or SRVarHash[newAlmt].bp2 < newAlmt.bp < other_bp \
                            or other_bp < newAlmt.bp < SRVarHash[newAlmt].bp2):

                            SRVarHash[newAlmt].bp3 = other_bp
                            SRVarHash[newAlmt].bp3tid = other_bp_tid
                            SRVarHash[newAlmt].n_changes+=1
                        elif newAlmt.tid == newAlmt.tid_2 and SRVarHash[newAlmt].bp2-slop/2 <= other_bp \
                            <= SRVarHash[newAlmt].bp2+slop/2 and l_orient != SRVarHash[newAlmt].l_orient:
                            #if 3rd bp unset till end, then call it an inversion if this condition is fulfilled
                            SRVarHash[newAlmt].insToInv=1
            ## FORM NEW SR VARIANT
            else:
                newAlmt.bp = sr_bp1
                newAlmt.tid = sr_bp1_tid
                newAlmt.tid_2 = sr_bp2_tid
                newVariant = newSRVar()
                newVariant.bp2 = sr_bp2
                newVariant.support.append(SRFrag)
                newVariant.l_orient = l_orient
                newVariant.r_orient = r_orient
                if newAlmt.tid == newAlmt.tid_2 and swap==0:
                    newVariant.swapped = 0
                    if l_orient == r_orient:
                        newVariant.typeSV = "DEL_INS"
                    else:
                        newVariant.typeSV = "INV_POSS"
                elif newAlmt.tid == newAlmt.tid_2 and swap==1:
                    newVariant.typeSV = "TD_I"
                    newVariant.swapped = 1
                    #$handle this case in INS_I matches
                    if l_orient != r_orient:
                        newVariant.typeSV = "INS_I"
                elif newAlmt.tid != newAlmt.tid_2:
                    newVariant.typeSV = "INS"
                    newVariant.swapped = 0
                    if l_orient != r_orient:
                        newVariant.typeSV = "INS_I"
                newVariant.isOriginal = 1
                if newAlmt not in SRVarHash:
                    SRVarHash[newAlmt] = newVariant

                list1 = range(int(sr_bp1-slop/2),int(sr_bp1+slop/2) + 1)
                list2 = range(int(sr_bp2-slop/2),int(sr_bp2+slop/2) + 1)
                for x in list1:
                    newVariant2 = newSRVar()
                    newVariant2.bp2 = newVariant.bp2
                    newVariant2.support.append(SRFrag)
                    newVariant2.l_orient = newVariant.l_orient
                    newVariant2.r_orient = newVariant.r_orient
                    newVariant2.typeSV = newVariant.typeSV
                    newVariant2.swapped = newVariant.swapped
                    newAlmtExt = SRAlmt()
                    newAlmtExt.tid = newAlmt.tid
                    newAlmtExt.tid_2 = newAlmt.tid_2
                    newAlmtExt.bp = x
                    if newAlmtExt not in SRVarHash:
                        SRVarHash[newAlmtExt] = newVariant2
                for x in list2:
                    newVariant2 = newSRVar()
                    newVariant2.bp2 = sr_bp1
                    newVariant2.support.append(SRFrag)
                    newVariant2.l_orient = newVariant.r_orient
                    newVariant2.r_orient = newVariant.l_orient
                    newVariant2.typeSV = newVariant.typeSV
                    newVariant2.swapped = newVariant.swapped
                    newAlmtExt = SRAlmt()
                    newAlmtExt.tid = newAlmt.tid_2
                    newAlmtExt.tid_2 = newAlmt.tid
                    newAlmtExt.bp = x
                    if newAlmtExt not in SRVarHash:
                        SRVarHash[newAlmtExt] = newVariant2

    ## WRITE REVISED PE VARIANTS TO FILE
    fAV.seek(0)
    for lineVM in fVM:
        lineVM_split = lineVM.split()
        varNumPE = int(lineVM_split[0])
        for lineAV in fAV:
            lineAV_split = lineAV.split()
            if varNumPE in SRtoPESuppList:
                lineAV_split[11] = lineAV_split[11] + "_SR"
                lineAV_split[3] = str(SRtoPESuppList[varNumPE][0])
                lineAV_split[4] = str(SRtoPESuppList[varNumPE][0] + 1)
                if len(SRtoPESuppFrags[varNumPE]) > minSRtoPEsupport and SRtoPESuppList[varNumPE][2] == -1:
                    if int(lineAV_split[6]) < SRtoPESuppList[varNumPE][1] < int(lineAV_split[7]):
                        lineAV_split[6] = str(SRtoPESuppList[varNumPE][1])
                        lineAV_split[7] = str(SRtoPESuppList[varNumPE][1] + 1)
                    elif int(lineAV_split[9]) < SRtoPESuppList[varNumPE][1] < int(lineAV_split[10]):
                        lineAV_split[9] = str(SRtoPESuppList[varNumPE][1])
                        lineAV_split[10] = str(SRtoPESuppList[varNumPE][1] + 1)
                    if (lineAV_split[1] == "DEL" or lineAV_split[1] == "TD" or lineAV_split[1] == "INV") \
                        and int(lineAV_split[3]) > int(lineAV_split[7]):
                        lineAV_split[3], lineAV_split[6] = lineAV_split[6], lineAV_split[3]
                        lineAV_split[4], lineAV_split[7] = lineAV_split[7], lineAV_split[4]
                # full insertion matches
                elif len(SRtoPESuppFrags[varNumPE]) > minSRtoPEsupport:
                    lineAV_split[6] = str(SRtoPESuppList[varNumPE][1])
                    lineAV_split[7] = str(SRtoPESuppList[varNumPE][1] + 1)
                    lineAV_split[9] = str(SRtoPESuppList[varNumPE][2])
                    lineAV_split[10] = str(SRtoPESuppList[varNumPE][2] + 1)
            lineAVJ = "\t".join(lineAV_split)
            fAVN.write("%s\n" %lineAVJ)
            break
        lineVMJ = "\t".join(lineVM_split)
        fVMN.write("%s" %lineVMJ)
        if varNumPE in SRtoPESuppList:
            for SRFrag in SRtoPESuppFrags[varNumPE]:
                fVMN.write(" %s" %SRFrag)
        fVMN.write("\n")

    ## POSTPROCESS DE NOVO SR VARIANTS AND WRITE TO FILE
    k = 0
    for SRVar in SRVarHash:
        k+=1
        #print SRVar, SRVarHash[SRVar],SRVarHash[SRVar].typeSV, SRVarHash[SRVar].count
        if SRVarHash[SRVar].count > 0:
            bpTemp = SRVar.bp
            bpTempMate = SRVarHash[SRVar].bp2
            chosenVar = SRAlmt()
            neighborSupport = []
            origSV = SRVar
            # check neighbor hash pairs and transfer to one with change in type (bona fide)
            # else pick 1 at random
            if SRVarHash[SRVar].write == -1:
                for x in range(int(bpTemp-slop-1), int(bpTemp + slop+1)):
                    SRVarExt = SRAlmt()
                    SRVarExt.tid = SRVar.tid
                    SRVarExt.tid_2 = SRVar.tid_2
                    SRVarExt.bp = x
                # if in same variant "symmetry group"
                if SRVarExt in SRVarHash and \
                    SRVarHash[SRVarExt].support[0] == SRVarHash[SRVar].support[0]:

                    if SRVarHash[SRVarExt].n_changes > 0 and chosenVar.bp == -1:
                        chosenVar = SRVarExt
                        SRVarHash[SRVarExt].write = 1
                    else:
                        SRVarHash[SRVarExt].write = 0
                        for ns in SRVarHash[SRVarExt].support[1:]:
                            neighborSupport.append(ns)
                    if SRVarHash[SRVarExt].isOriginal == 1:
                        origSV = SRVarExt

                # if none, check mate hash pairs and transfer to one with most changes in type
                # else pick 1 randomly
                for x in range(int(bpTempMate-slop -1), int(bpTempMate + slop +1)):
                    SRVarExt = SRAlmt()
                    SRVarExt.tid = SRVar.tid_2
                    SRVarExt.tid_2 = SRVar.tid
                    SRVarExt.bp = x
                    if SRVarExt in SRVarHash and \
                        SRVarHash[SRVarExt].support[0] == SRVarHash[SRVar].support[0]:
                        if SRVarHash[SRVarExt].n_changes > 0 and chosenVar.bp == -1:
                            chosenVar = SRVarExt
                            SRVarHash[SRVarExt].write = 1
                        else:
                            SRVarHash[SRVarExt].write = 0
                            for ns in SRVarHash[SRVarExt].support[1:]:
                                neighborSupport.append(ns)
                        if SRVarHash[SRVarExt].isOriginal == 1:
                            origSV = SRVarExt

                # if all neighbors unchanged, pick the original one among all neighbors
                if chosenVar.bp == -1:
                    chosenVar = origSV
                    SRVarHash[chosenVar].write = 1
                SRVarHash[chosenVar].support = \
                   SRVarHash[chosenVar].support + list(set(neighborSupport) - \
                   set(SRVarHash[chosenVar].support))
                SRVarHash[chosenVar].count = len(SRVarHash[chosenVar].support)

            if SRVarHash[SRVar].write == 1 and SRVarHash[SRVar].count >= min_vs:
                if SRVarHash[SRVar].typeSV == "INS_I" and \
                    SRVarHash[SRVar].insToInv == 1 and SRVarHash[SRVar].bp3 == -1:
                    SRVarHash[SRVar].typeSV == "INV"
                elif SRVarHash[SRVar].typeSV == "INS_I" and SRVarHash[SRVar].bp3 == -1:
                    #$can make this "INV" from "INV_POSS" if wish to be liberal
                    SRVarHash[SRVar].typeSV == "INV_POSS"
                elif (SRVarHash[SRVar].typeSV == "INS_I" or SRVarHash[SRVar].typeSV == "INS") \
                    and SRVar.tid_2 == SRVarHash[SRVar].bp3tid and abs(SRVarHash[SRVar].bp2 - \
                    SRVarHash[SRVar].bp3) < minSizeINS:
                    SRVarHash[SRVar].typeSV = "INS_POSS"
                elif (SRVarHash[SRVar].typeSV == "INS_I" or SRVarHash[SRVar].typeSV == "INS") \
                    and SRVar.tid_2 == SRVarHash[SRVar].bp3tid and SRVarHash[SRVar].bp2 > \
                    SRVarHash[SRVar].bp3:
                    SRVarHash[SRVar].bp2, SRVarHash[SRVar].bp3 = SRVarHash[SRVar].bp3,\
                        SRVarHash[SRVar].bp2

                if (SRVarHash[SRVar].typeSV == "DEL_INS" or SRVarHash[SRVar].typeSV == "TD_I" \
                    or SRVarHash[SRVar].typeSV == "INV" or SRVarHash[SRVar].typeSV \
                    == "INV_POSS") and SRVar.bp > SRVarHash[SRVar].bp2:
                    fAVN.write("%s %s %s %s %s %s %s %s %s %s %s %s %s\n" %(k+varNumPE+1,
                        SRVarHash[SRVar].typeSV, SRVar.tid_2, SRVarHash[SRVar].bp2,
                        SRVarHash[SRVar].bp2+1, SRVar.tid, SRVar.bp, SRVar.bp + 1,
                        SRVarHash[SRVar].bp3tid, SRVarHash[SRVar].bp3, SRVarHash[SRVar].bp3
                        + 1, "SR", SRVarHash[SRVar].count))
                else:
                    fAVN.write("%s %s %s %s %s %s %s %s %s %s %s %s %s\n" %(k+varNumPE+1,
                        SRVarHash[SRVar].typeSV, SRVar.tid, SRVar.bp, SRVar.bp + 1,
                        SRVar.tid_2, SRVarHash[SRVar].bp2, SRVarHash[SRVar].bp2 + 1,
                        SRVarHash[SRVar].bp3tid, SRVarHash[SRVar].bp3, SRVarHash[SRVar].bp3
                        + 1, "SR", SRVarHash[SRVar].count))

                fVMN.write("%s" %(k+varNumPE+1))
                for elem in SRVarHash[SRVar].support:
                    fVMN.write(" %s" %elem)
                fVMN.write("\n")

    bamfile.close()

if __name__ == "__main__":
    PARSER = argparse.ArgumentParser(description='Add split reads to support existing PE variants and create new SR variants')
    PARSER.add_argument('workDir', help='Work directory')
    PARSER.add_argument('variantMapFilePE', help='File containing PEvariant map, typically variantMap.pe.txt')
    PARSER.add_argument('allVariantFilePE', help='File containing list of PE variants, typically allVariants.pe.txt')
    PARSER.add_argument('bamFileSR', help='File containing all split reads, name-sorted')
    PARSER.add_argument('-d', dest='debug', action='store_true',
                        help='print debug information')
    PARSER.add_argument('-s', default=8.0, dest='slop', type=float, help='SR breakpoint slop')
    PARSER.add_argument('-f', default=0, dest='refRate', type=int, help='Subsample every so many split reads')
    PARSER.add_argument('-m', default=3, dest='min_vs', type=int,
        help='Minimum support for SR variants')
    PARSER.add_argument('-q', default=10, dest='mapThresh', type=int, help='SR Mapping quality threshold')
    PARSER.add_argument('-i', default=None, dest='ignoreBED',
        help='Exclude-regions file in BED format')
    PARSER.add_argument('-c', default=None, dest='ignoreChr',
        help='File listing chromosomes to exclude from analysis')
    PARSER.add_argument('-n', default=4, dest='minSizeINS', type=int,
        help='Minimum size for SR INS calls')
    PARSER.add_argument('-t', default=3, dest='minSRtoPEsupport', type=int,
        help='Minimum support for SR-only variants')
    ARGS = PARSER.parse_args()

    LEVEL = logging.INFO
    if ARGS.debug:
        LEVEL = logging.DEBUG

    logging.basicConfig(level=LEVEL,
                        format='%(asctime)s %(levelname)s %(message)s',
                        datefmt='%m/%d/%Y %I:%M:%S %p')

    addSplitReads(ARGS.workDir, ARGS.variantMapFilePE, ARGS.allVariantFilePE,
                  ARGS.bamFileSR, ARGS.slop, ARGS.refRate, ARGS.min_vs,
                  ARGS.mapThresh, ARGS.ignoreChr, ARGS.minSizeINS,
                  ARGS.minSRtoPEsupport, ARGS.ignoreBED)

    logging.shutdown()