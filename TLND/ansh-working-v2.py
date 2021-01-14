#!/usr/bin/env python
"""
A heuristic approach for two-level network design - rural electrification
Initial: Ayse Selin Kocaman ,ask2170@columbia.edu
Improvements: Simone Fobi, sf2786@columbia.edu
"""

import os
import sys
import time
import copy
import CMST_dfs_OLD
import gc
import collections
from heapq import heappush, heappop
from osgeo import ogr
import network
import fileRW
# from scipy.spatial import distance as DST
import itertools
import numpy as np
import shutil
# import fiona
import pandas as pd
import sys

# import geopandas as gpd
# import shapely.wkt
print('HERE')

class Usage(Exception):
    def __init__(self, msg):
        self.msg = msg


class Error(Exception):
    def __init__(self, msg):
        self.msg = msg


def mergeCluster(ClusterByNode, NodesByClusterID, Centers, segment):
    center1, center2 = segment.getNodes()

    centerX = (center1.getWeight() * center1.getCenterX()
               + center2.getWeight() * center2.getCenterX()) / (center2.getWeight() + center1.getWeight())
    centerY = (center1.getWeight() * center1.getCenterY()
               + center2.getWeight() * center2.getCenterY()) / (center2.getWeight() + center1.getWeight())

    weight = center2.getWeight() + center1.getWeight()
    baseClusterID = min(ClusterByNode[center1], ClusterByNode[center2])
    mergingClusterID = max(ClusterByNode[center1], ClusterByNode[center2])

    NodesByClusterID[baseClusterID].extend(NodesByClusterID.pop(mergingClusterID))

    Centers[baseClusterID].setXY(centerX, centerY)
    Centers[baseClusterID].setWeight(weight)

    del Centers[mergingClusterID]

    for node in NodesByClusterID[baseClusterID]:
        ClusterByNode[node] = baseClusterID


def generateDictsFromShp(shapeFile, outputPath):
    'Reads nodes and node weights from a point shapefile.'
    rootDir, fc = os.path.split(shapeFile)
    file, ext = os.path.splitext(fc)

    if not os.path.exists(outputPath):
        try:
            os.mkdir(outputPath)
        except:
            print("ERROR: could not create new directory", outputPath)

    ds = ogr.Open(shapeFile)
    ptLayer = ds.GetLayer(0)

    nodesByClusterID = collections.defaultdict(list)
    clusterByNode = {}
    nodes = {}
    centers = {}
    LVCostDict = {}
    feat = ptLayer.GetNextFeature()
    nodes_weights_output = []

    np.random.seed(7)
    indices = np.random.permutation(ptLayer.GetFeatureCount())
    high = indices[:int(0.3 * ptLayer.GetFeatureCount())]

    while feat is not None:
        nodeWeight = 1
        geomRef = feat.GetGeometryRef()
        FID = feat.GetFID()
        x = geomRef.GetX()
        y = geomRef.GetY()

        # Trying putting nearest neigbors to every customer


        if FID in high:
            nodeDemand = 100  # at xx kWh/ month
        else:
            nodeDemand = 30
        nodes[FID] = network.Node(FID, x, y, nodeWeight,nodeDemand)
        centers[FID] = network.Node(FID, x, y, nodeWeight,nodeDemand)
        clusterByNode[nodes[FID]] = FID
        nodesByClusterID[FID].append(nodes[FID])
        LVCostDict[FID] = 0
        nodes_weights_output.append([x,y,nodeWeight])
        feat = ptLayer.GetNextFeature()
    ds.Destroy()
    nodes_weights_output = pd.DataFrame(nodes_weights_output,columns=['x','y','weights'])
    return nodesByClusterID, clusterByNode, nodes, centers, LVCostDict ,nodes_weights_output


def generateSegments(centers, searchRadius):
    segments = []
    nodeCopy = centers.copy()

    segID = 0
    for startNode in centers.values():
        del nodeCopy[startNode.getID()]
        for endNode in nodeCopy.values():
            dist = ((startNode.getX() - endNode.getX()) ** 2 +
                    (startNode.getY() - endNode.getY()) ** 2) ** (.5)
            if dist < searchRadius:
                segments.append(network.Seg(segID, startNode, endNode, dist))
                segID += 1
    return segments


def maxInClusterDist(centerNode, nodesByClusterID):
    maxdist = 0
    for node in nodesByClusterID[centerNode.getID()]:
        dist = ((centerNode.getX() - node.getX()) ** 2 +
                (centerNode.getY() - node.getY()) ** 2) ** (.5)
        if dist >= maxdist:
            maxdist = dist
    return maxdist


def maxTempInClusterDist(segment, ClusterByNode, nodesByClusterID):
    maxDist = 0

    tempCenter1, tempCenter2 = segment.getNodes()

    tempCenterX = (tempCenter1.getWeight() * tempCenter1.getX()
                   + tempCenter2.getWeight() * tempCenter2.getX()) / (tempCenter2.getWeight() + tempCenter1.getWeight())
    tempCenterY = (tempCenter1.getWeight() * tempCenter1.getY()
                   + tempCenter2.getWeight() * tempCenter2.getY()) / (tempCenter2.getWeight() + tempCenter1.getWeight())
    for node in nodesByClusterID[ClusterByNode[segment.getNode1()]]:
        dist = ((tempCenterX - node.getX()) ** 2 + (tempCenterY - node.getY()) ** 2) ** (.5)
        if dist >= maxDist:
            maxDist = dist

    for node in nodesByClusterID[ClusterByNode[segment.getNode2()]]:
        dist = ((tempCenterX - node.getX()) ** 2 + (tempCenterY - node.getY()) ** 2) ** (.5)
        if dist >= maxDist:
            maxDist = dist

    return maxDist, tempCenterX, tempCenterY


def loggers(log_filename, initial=False, data=None):
    if initial:
        with open(log_filename, 'w') as src:
            src.write("")
    else:
        with open(log_filename, 'a') as src:
            src.write(str(data) + "\n")


def totalInClusterCost(nodesByClusterID, centers):
    totalCost = 0
    for centerID in centers.keys():
        for node in nodesByClusterID[centerID]:
            totalCost += ((node.getX() - centers[centerID].getX()) ** 2 +
                          (node.getY() - centers[centerID].getY()) ** 2) ** (.5)
    return totalCost


def kruskalsAlg(segments, nodes):
    'Kruskal\'s algorithm for finding a minimum spanning tree'
    segments.sort(key=lambda obj: obj.getWeight())
    tree = network.Network()
    numNodes = len(nodes)

    for segment in segments:
        node1 = segment.getNode1()
        node2 = segment.getNode2()
        node1InNet = tree.inNet(node1)
        node2InNet = tree.inNet(node2)

        if (not node1InNet and not node2InNet) or (node1InNet != node2InNet):
            tree.addSeg(segment)
        else:
            if node1InNet and node2InNet and \
                    (tree.getNetID(node1) != tree.getNetID(node2)):
                tree.addSeg(segment)
        if tree.numNodes() > numNodes:
            break
    return tree, segments


def primsAlg(segments, numNodes, firstNodeID, nodeDict):
    'Prim\'s Algorithm for finding a minimum spanning tree'

    tree = network.Network()
    segHeap = []

    # Find the shortest segment emanating from the node with the firstNodeID
    try:
        segs = nodeDict[firstNodeID]
    except KeyError:
        return tree

    leastWeight = None
    for seg in segs:
        if (leastWeight == None):
            leastWeight = seg.getWeight()
            firstSeg = seg
        elif (seg.getWeight() < leastWeight):
            leastWeight = seg.getWeight()
            firstSeg = seg
    tree.addSeg(firstSeg)

    # Starter to algorithm
    # Add the segs emanating from the first two endpoints to the heap
    for endNode in [firstSeg.getNode1(), firstSeg.getNode2()]:
        addToHeap(segHeap, nodeDict[endNode.getID()])

    # Pick best from heap and repeat
    while tree.numNodes() < numNodes:
        try:
            # Get best segment from heap
            seg = heappop(segHeap)
        except:
            # Tree is finished (not all nodes contained).
            break
        node1, node2 = seg.getNodes()
        node1InNet = tree.inNet(node1)
        node2InNet = tree.inNet(node2)
        # Add the seg if it's terminal node isn't already in the cluster.
        if (not node1InNet) or (not node2InNet):
            if not node1InNet:
                endNode = node1
            else:
                endNode = node2
            tree.addSeg(seg)
            # Add all emanating segs to the heap:
            # nodeDict returns all segments coming out from the endNode
            # endNode is the node that is outside of the tree
            addToHeap(segHeap, nodeDict[endNode.getID()])
            # And we are sure that everything in the heap is adjacent to the tree because
            # we only add the adjacent segments in the first place using nodeDict
    return tree


def addToHeap(heap, newSegs):
    'Adds new segments to the segHeap.'
    for seg in newSegs:
        heappush(heap, seg)
    return heap


def buildAssocDict(segments):
    'Builds dictionary with nodeID key where values are segs from/to that node'
    # ipdb.set_trace()
    segList = {}
    for seg in segments:
        node1, node2 = seg.getNodes()
        for nodeID in [node1.getID(), node2.getID()]:
            if nodeID in segList.keys():
            # if segList.has_key(nodeID):
                segList[nodeID].append(seg)
            else:
                segList[nodeID] = [seg]
    return segList


def convertDictToArray(centers):
    array = np.zeros((len(centers), 2))
    for c in range(len(centers)):
        node = centers[c]
        array[c, :] = [node.getX(), node.getY()]
    return array
#
# def simonegenerateSegments(centers, searchRadius):
#     X = convertDictToArray(centers)
#     uniqueIDX = list(itertools.combinations(range(X.shape[0]), 2))
#     distsAll = DST.pdist(X)
#     condition = distsAll < searchRadius
#     dt = np.dtype('int,int')
#
#     distsInRadius = distsAll[condition]
#     idxInRadius = np.array(uniqueIDX, dtype=dt)[condition]
#
#     segments = []
#     segID = 0
#     for k in range(len(distsInRadius)):
#         segments.append(network.Seg(segID, centers[idxInRadius[k][0]], centers[idxInRadius[k][1]], distsInRadius[k]))
#         segID += 1
#
#     return segments

def check_number_connected(inputs):
    nodesbycluster, centers = inputs
    num_connected = 0
    true_centers = {}
    true_nodesbycluster = {}
    for k,v in nodesbycluster.items():
        if len(v) > 1:
            num_connected += len(v)
            true_centers[k] = centers[k]
            true_nodesbycluster[k] = v
    return  num_connected, true_nodesbycluster, true_centers

def get_distance(centroidX, centroidY, nodelist):
    dist = 0
    for node in nodelist:
        tmp_dist = ((centroidX - node.getX()) ** 2 + (centroidY - node.getY()) ** 2) ** (.5)
        dist += tmp_dist
    return dist

def generateWeightedSegments(centers, searchRadius, roi_years, cost_per_kwh, LV, demand_weight= 0, LVCostDict = None):
    # this function determines the easiest to connect segments based on a ranking mechanism
    segments = []
    nodeCopy = centers.copy()
    segID = 0

    max_dist = 0
    max_delta = -100000000000000000
    for startNode in centers.values():
        del nodeCopy[startNode.getID()]
        for endNode in nodeCopy.values():

            # if [startNode.getID(), endNode.getID()] not in all_ready_checked_list:
            dist = ((startNode.getX() - endNode.getX()) ** 2 +
                        (startNode.getY() - endNode.getY()) ** 2) ** (.5)
            total_line_cost = (dist * LV) + LVCostDict[startNode.getID()] + LVCostDict[endNode.getID()]
            total_demand = startNode.getDemand() + endNode.getDemand()  # calculates the demand from both nodes
            revenue = total_demand * roi_years * 12 * cost_per_kwh
            delta = revenue - total_line_cost

            if dist < searchRadius:
                segments.append(network.Seg(segID, startNode, endNode, dist, delta))
                segID += 1
                if max_dist < dist:
                    max_dist = dist
                if max_delta < delta:
                    max_delta = delta
            # else:
            #     pass
    # import ipdb;ipdb.set_trace()
    segments_by_rank = []
    # note you can do standardization instead of normalization
    for seg in segments:
        rank = (1.0 - (seg.getWeight()/max_dist)) * (1-demand_weight) + (seg.getDemand()/ max_delta) * demand_weight
        segments_by_rank.append(network.Seg(seg.getID(), seg.getNode1(), seg.getNode2(), seg.getWeight(), rank))
        # seg.setDemand(rank)

    return segments_by_rank


def generateWeightedSegmentsLV_if(centers, searchRadius_LV,roi_years, cost_per_kwh, LV, demand_weight= 0, LVCostDict = None):
    # this function determines the easiest to connect segments based on a ranking mechanism
    segments = []
    nodeCopy = centers.copy()
    segID = 0

    max_dist = 0
    max_delta = -100000000000000000
    for startNode in centers.values():
        del nodeCopy[startNode.getID()]
        for endNode in nodeCopy.values():

            #if [startNode.getID(), endNode.getID()] not in all_ready_checked:
                dist = ((startNode.getX() - endNode.getX()) ** 2 +
                            (startNode.getY() - endNode.getY()) ** 2) ** (.5)
                total_line_cost = (dist * LV) + LVCostDict[startNode.getID()] + LVCostDict[endNode.getID()]
                total_demand = startNode.getDemand() + endNode.getDemand()  # calculates the demand from both nodes
                revenue = total_demand * roi_years * 12 * cost_per_kwh
                delta = revenue - total_line_cost

                #import ipdb; ipdb.set_trace()

                # Location of the temporary transformer:
                # Initializing with the nodes as centers
                tempCenter1 = startNode; tempCenter2 = endNode
                #Locating the centroid of the points
                tempCenterX = (tempCenter1.getWeight() * tempCenter1.getX()
                       + tempCenter2.getWeight() * tempCenter2.getX()) / (tempCenter2.getWeight() + tempCenter1.getWeight())
                tempCenterY = (tempCenter1.getWeight() * tempCenter1.getY()
                       + tempCenter2.getWeight() * tempCenter2.getY()) / (tempCenter2.getWeight() + tempCenter1.getWeight())

                # The distance of nodes from the centroid:
                distnode1fromT = ((startNode.getX() - tempCenterX) ** 2 +
                            (startNode.getY() - tempCenterY) ** 2) ** (.5)

                distnode2fromT = ((endNode.getX() - tempCenterX) ** 2 +
                            (endNode.getY() - tempCenterY) ** 2) ** (.5)

                # SearchRadius = distFromT in this case!

                if (distnode1fromT < searchRadius_LV) & (distnode2fromT < searchRadius_LV):
                #if dist < searchRadius: # Just put distFromT?
                    segments.append(network.Seg(segID, startNode, endNode, dist, delta))
                    segID += 1
                    if max_dist < dist:
                        max_dist = dist
                    if max_delta < delta:
                        max_delta = delta
            # else:
            #     pass
    #import ipdb;ipdb.set_trace()
    segments_by_rank = []
    # note you can do standardization instead of normalization
    for seg in segments:
        rank = (1.0 - (seg.getWeight()/max_dist)) * (1-demand_weight) + (seg.getDemand()/ max_delta) * demand_weight
        segments_by_rank.append(network.Seg(seg.getID(), seg.getNode1(), seg.getNode2(), seg.getWeight(), rank))
        # seg.setDemand(rank)

    return segments_by_rank


def generateWeightedSegmentsLV_else(centers,searchRadius_LV,  all_ready_checked, roi_years, cost_per_kwh, LV, demand_weight= 0, LVCostDict = None):
    # this function determines the easiest to connect segments based on a ranking mechanism
    #import ipdb; ipdb.set_trace()  
    segments = []
    nodeCopy = centers.copy()
    segID = 0

    max_dist = 0
    max_delta = -100000000000000000
    for startNode in centers.values():
        del nodeCopy[startNode.getID()]
        for endNode in nodeCopy.values():

            if [startNode.getID(), endNode.getID()] not in all_ready_checked:
                dist = ((startNode.getX() - endNode.getX()) ** 2 +
                            (startNode.getY() - endNode.getY()) ** 2) ** (.5)
                total_line_cost = (dist * LV) + LVCostDict[startNode.getID()] + LVCostDict[endNode.getID()]
                total_demand = startNode.getDemand() + endNode.getDemand()  # calculates the demand from both nodes
                revenue = total_demand * roi_years * 12 * cost_per_kwh
                delta = revenue - total_line_cost

                #import ipdb; ipdb.set_trace()

                # Location of the temporary transformer:
                # Initializing with the nodes as centers
                tempCenter1 = startNode; tempCenter2 = endNode
                #Locating the centroid of the points
                tempCenterX = (tempCenter1.getWeight() * tempCenter1.getX()
                       + tempCenter2.getWeight() * tempCenter2.getX()) / (tempCenter2.getWeight() + tempCenter1.getWeight())
                tempCenterY = (tempCenter1.getWeight() * tempCenter1.getY()
                       + tempCenter2.getWeight() * tempCenter2.getY()) / (tempCenter2.getWeight() + tempCenter1.getWeight())

                # The distance of nodes from the centroid:
                distnode1fromT = ((startNode.getX() - tempCenterX) ** 2 +
                            (startNode.getY() - tempCenterY) ** 2) ** (.5)

                distnode2fromT = ((endNode.getX() - tempCenterX) ** 2 +
                            (endNode.getY() - tempCenterY) ** 2) ** (.5)

                # SearchRadius = distFromT in this case!

                if (distnode1fromT < searchRadius_LV) & (distnode2fromT < searchRadius_LV):
                #if dist < searchRadius: # Just put distFromT?
                    segments.append(network.Seg(segID, startNode, endNode, dist, delta))
                    segID += 1
                    if max_dist < dist:
                        max_dist = dist
                    if max_delta < delta:
                        max_delta = delta
            # else:
            #     pass
    #import ipdb;ipdb.set_trace()
    segments_by_rank = []
    # note you can do standardization instead of normalization
    for seg in segments:
        rank = (1.0 - (seg.getWeight()/max_dist)) * (1-demand_weight) + (seg.getDemand()/ max_delta) * demand_weight
        segments_by_rank.append(network.Seg(seg.getID(), seg.getNode1(), seg.getNode2(), seg.getWeight(), rank))
        # seg.setDemand(rank)

    return segments_by_rank    


# def run(centers, nodesByClusterID, clusterByNode, LVCostDict, sr, MV, LV, TCost, distFromT, maxLVLenghtInCluster,
#         outputDir, logfilename,max_connection):
def run(centers, nodesByClusterID, clusterByNode, LVCostDict, sr, searchRadius_LV, MV, LV, TCost, distFromT, investment,
            cost_per_kwh,roi_years, maxLVLenghtInCluster,outputDir, logfilename,max_connection,demand_weight):
    print("First Stage starts without MST")
    #import ipdb; ipdb.set_trace()
    sumLVCostAtEachStep = {}
    minCenters = copy.deepcopy(centers)
    all_ready_checked = []   
    segments = generateWeightedSegmentsLV_if(minCenters, searchRadius_LV,roi_years,cost_per_kwh,LV,demand_weight,LVCostDict)
    
    # To write total cost to a text file
    statFile = outputDir + os.sep + "TotalCost_FirstStage.txt"
    outFile = open(statFile, "w")

    minTotalCost = len(centers) * TCost
    outFile.write("%(minTotalCost)f\n" % vars())
    minLVCostDict = copy.deepcopy(LVCostDict)

    minNodesByClusterID = copy.deepcopy(nodesByClusterID)
    minClusterByNode = copy.deepcopy(clusterByNode)
    # minSeg = min(segments, key=lambda obj: obj.getWeight())
    minSeg = max(segments, key=lambda obj: obj.getDemand())


    if minSeg.getWeight() <= distFromT * 2:
        maxDist = 0
    else:
        maxDist = distFromT + 10
        print("NO CLUSTER POSSIBLE")

    tempCenter1, tempCenter2 = minSeg.getNodes()
    tempCenterX = (tempCenter1.getWeight() * tempCenter1.getX()
                   + tempCenter2.getWeight() * tempCenter2.getX()) / (tempCenter2.getWeight() + tempCenter1.getWeight())
    tempCenterY = (tempCenter1.getWeight() * tempCenter1.getY()
                   + tempCenter2.getWeight() * tempCenter2.getY()) / (tempCenter2.getWeight() + tempCenter1.getWeight())
    i = len(centers)
    initial = True
    loggers(logfilename, initial)
    initial = False
    connected = 0
    
    newTotalCost = 0

    SegmentsToCheckID = []
    for seg in segments:
        SegmentsToCheckID.append(seg.getID())

 

    #while (connected <= max_connection):
    while (maxDist <= distFromT) & (connected <= max_connection):  

        i -= 1
        cur_token = 'stage1 ' + str(i)
        loggers(logfilename, initial, cur_token)
        
        tmp_nodesByClusterID = copy.deepcopy(nodesByClusterID)
        tmp_centers = copy.deepcopy(centers)
        tmp_clusterByNode = copy.deepcopy(clusterByNode)
        tmp_LVCostDict = copy.deepcopy(LVCostDict)


        center1, center2 = minSeg.getNodes()
        weight = center2.getWeight() + center1.getWeight()
        baseClusterID = min(clusterByNode[center1], clusterByNode[center2])
        mergingClusterID = max(clusterByNode[center1], clusterByNode[center2])
        nodesByClusterID[baseClusterID].extend(nodesByClusterID.pop(mergingClusterID))


        centers[baseClusterID].setXY(tempCenterX, tempCenterY)
        centers[baseClusterID].setWeight(weight)

        del centers[mergingClusterID]
        # What is the purpose of this?

        for node in nodesByClusterID[baseClusterID]:
            clusterByNode[node] = baseClusterID

        all_ready_checked.append([baseClusterID, mergingClusterID])           

        # segments = generateSegments(centers, sr)

        # Deleting the checked Segments:
        #for i, o in enumerate(SegmentsToCheck):
        #    if o.getID() == minSeg.getID():
        #        del SegmentsToCheck[i]
        #        break


        TotalTransformerCost = len(centers) * TCost
        
        gc.collect()
        segmentsCMST, LVCostDict[baseClusterID] = CMST_dfs_OLD.CMST(nodesByClusterID[baseClusterID],
                                                                    maxLVLenghtInCluster,
                                                                    centers[baseClusterID])

        # sums the cost
        sumLVCostAtEachStep[len(centers)] = sum(LVCostDict.values()) * LV
        oldcost = newTotalCost
        newTotalCost = TotalTransformerCost + (sum(LVCostDict.values())) * LV


        outFile.write("%i %f\n" % (i, sumLVCostAtEachStep[len(centers)]))

        

        if (newTotalCost <= minTotalCost):
            minNodesByClusterID = copy.deepcopy(nodesByClusterID)
            # minTree=copy.deepcopy(newTree)
            minCenters = copy.deepcopy(centers)
            minLVCostDict = LVCostDict.copy()
            minTotalCost = newTotalCost
            minClusterByNode = copy.deepcopy(clusterByNode)
            connected, trueNodesByClusterID, trueMinCenters = check_number_connected([minNodesByClusterID,minCenters])

            # Adding this inside the statement:

            del LVCostDict[mergingClusterID]

            # Moved this from the chunk
            segments = generateWeightedSegmentsLV_if(minCenters, searchRadius_LV, roi_years, cost_per_kwh, LV, demand_weight,LVCostDict)
            
            #print("New total cost is: {}, difference is {}, The number connected is {}".format(newTotalCost, - newTotalCost + oldcost,
            #            connected))

            #if connected >= 284:
            #    import ipdb; ipdb.set_trace()

        else:
            minNodesByClusterID= copy.deepcopy(tmp_nodesByClusterID)
            minCenters = copy.deepcopy(tmp_centers)
            minClusterByNode = copy.deepcopy(tmp_clusterByNode)
            LVCostDict = copy.deepcopy(tmp_LVCostDict)
            segments = generateWeightedSegmentsLV_else(minCenters, searchRadius_LV, all_ready_checked, roi_years, cost_per_kwh, LV, demand_weight,LVCostDict)

        # Calculate maxDist below for next graph and continue if it is less than 500
        #segments = generateWeightedSegmentsLV(minCenters, sr, all_ready_checked, roi_years, cost_per_kwh, LV, demand_weight,LVCostDict)

        try:  # to check if there is a segment on the graph or there is only one cluster  # bir tane break eden varsa bile devamini check ediyor!!!!!
            # seems this looks for the shortest segment with the lv less that distFromT
            minSeg = max(segments, key=lambda obj: obj.getDemand()) # finds closest 2 points
            maxDist, tempCenterX, tempCenterY = maxTempInClusterDist(minSeg, clusterByNode, nodesByClusterID) # find the largest distance to centroid of minSeg
            if maxDist > distFromT: # if largest distance > 500 meters
                segments.sort(key=lambda obj: obj.getDemand(), reverse=True) # sort by highest to lowest rank

                for seg in segments:
                    if seg.getWeight() > distFromT * 2: # distance greater than 1000 skip
                        break
                    else: # if distance is okay check if there are 2 closer points
                        maxDist, tempCenterX, tempCenterY = maxTempInClusterDist(seg, clusterByNode, nodesByClusterID)
                        if maxDist <= distFromT:
                            minSeg = seg  ## identifies a new minSeg to go to if there is still room to add to the LV
                            break # finds the next minimum segment to go to
        except:
            break           


    outFile.close()
    print("Second Stage starts with MST")
    if len(trueMinCenters) == len(centers) or len(trueMinCenters) == 1:
        # segments_ST = generateSegments(trueMinCenters, sr)
        segments_ST = generateWeightedSegments(trueMinCenters, sr, roi_years, cost_per_kwh, LV, demand_weight, LVCostDict)
        nodeDict = buildAssocDict(segments_ST)
        minTree = primsAlg(segments_ST, len(trueMinCenters), 0, nodeDict)
        minTotalCost_ST = minTree.getTotalEdgeWeight() * MV + minTotalCost
        return minTotalCost_ST, minTree, trueMinCenters, nodesByClusterID, sum(LVCostDict.values()) * LV

    centers_ST = copy.deepcopy(trueMinCenters)
    LVCostDict_ST = minLVCostDict

    print("centers", len(centers_ST))

    # segments_ST = generateSegments(centers_ST, sr)
    segments_ST = generateWeightedSegments(centers_ST, sr, roi_years, cost_per_kwh, LV, demand_weight, LVCostDict_ST)

    # To write total cost to a text file
    statFile = outputDir + os.sep + "TotalCost_SecondStage.txt"
    outFile = open(statFile, "w")

    nodeDict = buildAssocDict(segments_ST)

    minTree = primsAlg(segments_ST, len(centers_ST), [*nodeDict.keys()][0], nodeDict)  # 0 is the starting node of Prims algorithm
    i = len(centers_ST)
    minTotalCost_ST = minTree.getTotalEdgeWeight() * MV + len(centers_ST) * TCost + (sum(minLVCostDict.values())) * LV
    outFile.write(
        "%i %f %f %f\n" % (i, (sum(minLVCostDict.values())) * LV, minTree.getTotalEdgeWeight() * MV, minTotalCost_ST))

    minLVCostSum_ST = 9999999999999999  # a big number
    nodesByClusterID_ST = copy.deepcopy(minNodesByClusterID)
    clusterByNode_ST = copy.deepcopy(minClusterByNode)
    try:
        # given the tx location
        minSeg_ST = max(segments_ST, key=lambda obj: obj.getDemand()) #
        maxDist, tempCenterX, tempCenterY = maxTempInClusterDist(minSeg_ST, clusterByNode_ST, nodesByClusterID_ST)
        if maxDist > distFromT:
            segments_ST.sort(key=lambda obj: obj.getWeight())

            for seg in segments_ST:
                if seg.getWeight() > distFromT * 2:
                    break  # break from for loop
                else:
                    maxDist, tempCenterX, tempCenterY = maxTempInClusterDist(seg, clusterByNode_ST, nodesByClusterID_ST)
                    if maxDist <= distFromT:
                        minSeg_ST = seg
                        break  # break from for loop
    except:
        return minTotalCost_ST, minTree, centers_ST, nodesByClusterID_ST, sum(LVCostDict_ST.values()) * LV

    minNodesByClusterID_ST = copy.deepcopy(minNodesByClusterID)
    minCenters_ST = copy.deepcopy(trueMinCenters)

    if minSeg_ST.getWeight() <= distFromT * 2:
        maxDist = 0
    else:
        maxDist = distFromT + 10
        print("NO CLUSTER POSSIBLE")

    tempCenter1, tempCenter2 = minSeg_ST.getNodes()

    tempCenterX = (tempCenter1.getWeight() * tempCenter1.getX()
                   + tempCenter2.getWeight() * tempCenter2.getX()) / (tempCenter2.getWeight() + tempCenter1.getWeight())
    tempCenterY = (tempCenter1.getWeight() * tempCenter1.getY()
                   + tempCenter2.getWeight() * tempCenter2.getY()) / (tempCenter2.getWeight() + tempCenter1.getWeight())

    initial = False
    i = len(minCenters)
    while (maxDist <= distFromT):

        i -= 1
        if i % 20 == 0:
            cur_token = 'stage2 ' + str(i)
            loggers(logfilename, initial, cur_token)
        center1, center2 = minSeg_ST.getNodes()

        weight = center2.getWeight() + center1.getWeight()
        additional_LV = get_distance(tempCenterX, tempCenterY, [center1, center2])

        baseClusterID = min(clusterByNode_ST[center1], clusterByNode_ST[center2])

        mergingClusterID = max(clusterByNode_ST[center1], clusterByNode_ST[center2])

        nodesByClusterID_ST[baseClusterID].extend(nodesByClusterID_ST.pop(mergingClusterID))

        centers_ST[baseClusterID].setXY(tempCenterX, tempCenterY)
        centers_ST[baseClusterID].setWeight(weight)
        
        del centers_ST[mergingClusterID]

        for node in nodesByClusterID_ST[baseClusterID]:
            clusterByNode_ST[node] = baseClusterID

        # segments_ST = generateSegments(centers_ST, sr)
        segments_ST = generateWeightedSegments(centers_ST, sr, roi_years, cost_per_kwh, LV, demand_weight, LVCostDict_ST)
        nodeDict = buildAssocDict(segments_ST)
        newTree = primsAlg(segments_ST, len(centers_ST), [*nodeDict.keys()][0], nodeDict)
        TotalMVCost_ST = newTree.getTotalEdgeWeight() * MV
        TotalTransformerCost_ST = len(centers_ST) * TCost
        gc.collect()

        newTotalCost_ST = TotalMVCost_ST + TotalTransformerCost_ST + (sum(LVCostDict_ST.values())) + additional_LV * LV

        if (newTotalCost_ST <= minTotalCost_ST):
            minNodesByClusterID_ST = copy.deepcopy(nodesByClusterID_ST)
            minTree = copy.deepcopy(newTree)
            minCenters_ST = copy.deepcopy(centers_ST)
            minLVCostSum_ST = (sum(LVCostDict_ST.values())) + additional_LV * LV #sumLVCostAtEachStep[len(centers_ST)]
            minTotalCost_ST = newTotalCost_ST
            LVCostDict_ST[baseClusterID] += additional_LV * LV


        # Calculate maxDist below for next graph and continue if it is less than 500

        try:  # to check if there is a segment on the graph or there is only one cluster
            minSeg_ST = max(segments_ST, key=lambda obj: obj.getDemand())
            maxDist, tempCenterX, tempCenterY = maxTempInClusterDist(minSeg_ST, clusterByNode_ST, nodesByClusterID_ST)

            if maxDist > distFromT:
                segments_ST.sort(key=lambda obj: obj.getWeight())

                for seg in segments_ST:
                    if seg.getWeight() > distFromT * 2:
                        break
                    else:
                        maxDist, tempCenterX, tempCenterY = maxTempInClusterDist(seg, clusterByNode_ST,
                                                                                 nodesByClusterID_ST)
                        if maxDist <= distFromT:
                            minSeg_ST = seg
                            break
        except Exception as err:
            print(err)
            break
    outFile.close()
    # import ipdb;ipdb.set_trace()
    return minTotalCost_ST, minTree, minCenters_ST, minNodesByClusterID_ST, minLVCostSum_ST


def addLVSeg(tree, centers, nodesByClusterID):  # single points line from the root
    SegID = 1000000

    for centerID in centers.keys():
        try:
            netID = tree.getNetID(centers[centerID])
        except:
            netID = 0
            tree._nodesByNetID[0] = []
            tree._network[netID] = []

        for node in nodesByClusterID[centerID]:
            length = ((node.getX() - centers[centerID].getX()) ** 2 +
                      (node.getY() - centers[centerID].getY()) ** 2) ** (.5)
            newSeg = network.Seg(SegID, node, centers[centerID], length)
            tree._netIDByNode[node] = netID
            tree._nodesByNetID[netID].append(node)
            tree._network[netID].append(newSeg)
    return tree


def writeLVDictToText(statsFile, Dict):
    'Writes LVCostDict to a text file for batchPrimsForTransformers.py.'
    outFile = open(statsFile, "w")
    for key in Dict.keys():
        LVCost = Dict[key] * 10
        outFile.write("%(key)i %(LVCost)f\n" % vars())
    outFile.close()
    return 0


def writeCenterSizeToText(statsFile, Dict):
    outFile = open(statsFile, "w")
    for key in Dict.keys():
        size = Dict[key].getWeight()
        outFile.write("%(size)i \n" % vars())
    outFile.close()
    return 0


def get_relevant_grids(txtpath, batch_num, total_num_batches):
    grid_files = []
    txt_files = os.listdir(txtpath)
    for txt in txt_files:
        with open(txtpath + txt) as src:
            content = src.readlines()
            for c in content:
                grid_files.append(c.strip())

    print("Number of grid files found", len(grid_files))
    step = int(np.ceil(len(grid_files) / total_num_batches))
    start = int(step * batch_num)
    stop = (start + step) - 1
    mygrids = grid_files[start:stop]
    return mygrids


def get_debug_grids(txtpath, batch_num, total_num_batches):
    grid_files = []
    txt_files = os.listdir(txtpath)
    for txt in txt_files:
        with open(txtpath + txt) as src:
            content = src.readlines()
            for c in content:
                grid_files.append(c.strip())
    print("Number of grid files found", len(grid_files))
    mygrids = grid_files[int(batch_num):int(batch_num + 1.0)]
    return mygrids


def get_debug_subgrids(txtpath, batch_num):
    # grid_files = []
    ward_files = os.listdir(txtpath)
    grid_files = sorted(ward_files)
    print("Number of grid files found", len(grid_files))
    mygrids = grid_files[int(batch_num):int(batch_num + 1.0)]
    mygrids = [os.path.join(txtpath, m) for m in mygrids]
    return mygrids


def get_relevant_wards(path, batch_num, total_num_batches):
    wards_file = os.listdir(path)
    wards = [os.path.join(path, c) for c in wards_file]
    print("Number of grid files found", len(wards))
    step = int(np.ceil(len(wards) / total_num_batches))
    start = int(step * batch_num)
    stop = (start + step) - 1
    mywards = wards[start:stop]
    return mywards


def check_start(start):
    val = start - np.floor(start)
    diffs = [val - 0, 1 - val]
    flag = np.argmin(diffs)
    if flag == 1:
        return int(np.ceil(start))
    else:
        return int(np.floor(start))


def get_scale_and_subgrids(grid, start, stop=None):
    # allowed_subgrid = np.arange(start,stop+1)
    subgrids = []
    for root, dirs, files in os.walk(grid):
        for name in files:
            if 'MV' not in name and 'FinalGrid' not in name:
                if 'scale' in root and '.shp' in name:
                    valid = int(name[:-4].split('_')[-1])
                    if valid == start:
                        subgrids.append(os.path.join(root, name))
                        return subgrids


def get_scale_and_subgrids_v2(grid, start, stop):
    # allowed_subgrid = np.arange(start,stop+1)
    subgrids = []
    for root, dirs, files in os.walk(grid):
        for name in files:
            if 'MV' not in name and 'FinalGrid' not in name:
                if 'scale' in root and '.shp' in name:
                    valid_stop = (name[:-4].split('/')[-1]).split('_')[-1]
                    valid_start = int((name[:-4].split('/')[-1]).split('_')[1])
                    if valid_start == start and valid_stop == stop:
                        subgrids.append(os.path.join(root, name))
                        return subgrids


def is_uncompleted(grid_file, subgrid_number):
    # files_in_subgrid = os.listdir(sub_grid)
    valid = True
    for root, dirs, files in os.walk(grid_file):
        for name in files:
            if 'scale' in root and 'modelOutput.txt' in name:
                cur_subgrid = int((name.split('_')[-1]).strip('modelOutput.txt'))
                if cur_subgrid == subgrid_number:
                    valid = False
    return valid


def is_notvisited(grid_file):
    valid = True
    for root, dirs, files in os.walk(grid_file):
        for name in files:
            if 'modelOutput.txt' in name:
                valid = False
    return valid

#
# def get_search_radius(input_file, buffer_r=1000):
#     bbox = fiona.open(input_file).bounds
#     radius = int(np.ceil((((bbox[2] - bbox[0]) ** 2) + ((bbox[3] - bbox[1]) ** 2)) ** 0.5) + buffer_r)
#     return radius

def convert_to_utm_shp(latlon_shp,output_file ,epsg = 'epsg:32637'):
    df = pd.read_csv(latlon_shp)
    df['LAT'] = df.centroid.apply(lambda x: shapely.wkt.loads(x).y)
    df['LON'] = df.centroid.apply(lambda x: shapely.wkt.loads(x).x)
    geo_df = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.LON, df.LAT))
    geo_df.crs= {'init': 'epsg:4326'}
    utm_df = geo_df.to_crs({'init':epsg})
    utm_df.to_file(output_file)
    return True


def main(cur_file):
    #searchRadius = 100000  # meters
    # Cost parameters:
    MV = 25  # Cost of MV per meter
    LV = 10  # Cost of LV per meter
    TCost = 2000  # Transformer Cost
    distFromT = 500  # Dmax, direct distance from transformers
    searchRadius = 10000  # Reducing the distance to search locally   
    searchRadius_LV = distFromT
    maxLVLenghtInCluster = 500  # Lmax
    # read shape file
    outputDir = cur_file[:-4]
    access_rate = float(sys.argv[1])  # penetration rate
    investment = 600000
    roi_years = 5
    cost_per_kwh = 0.05
    demand_weight = float(sys.argv[2])

    if os.path.isdir(outputDir):
        shutil.rmtree(outputDir)
    print(outputDir)
    logfilename = outputDir + 'modelStatus.txt'
    startTime = time.time()
    try:
        print("Generating Dictionaries")
        nodesByClusterID, clusterByNode, nodes, centers, LVCostDict ,node_weights_output = generateDictsFromShp(cur_file,
                                                                                           outputDir)
        connected = int(access_rate * len(nodes))
        
        node_weights_output.to_csv(os.path.join(outputDir,'node_weights.csv'))
        print("Run function starts...")
        # totalCost, tree, centers, nodesByClusterID, LVCostSum = run(centers, nodesByClusterID, clusterByNode,
        #                                                             LVCostDict, searchRadius, MV, LV, TCost,
        #                                                             distFromT,
        #                                                             maxLVLenghtInCluster, outputDir, logfilename,connected)
        #import ipdb; ipdb.set_trace()
        totalCost, tree, centers, nodesByClusterID, LVCostSum = run(centers, nodesByClusterID, clusterByNode,
                                                                    LVCostDict, searchRadius, searchRadius_LV, MV, LV, TCost,
                                                                    distFromT, investment, cost_per_kwh, roi_years,
                                                                    maxLVLenghtInCluster, outputDir, logfilename,connected,demand_weight)


        #import ipdb; ipdb.set_trace()

        # import ipdb;ipdb.set_trace()
        fileRW.genShapefile(tree, outputDir + ".prj", outputDir + os.sep + "MV.shp")

        statsFile1 = outputDir + os.sep + "LVCostDict.txt"
        statsFile2 = outputDir + os.sep + "CenterSize.txt"
        writeLVDictToText(statsFile1, LVCostDict)
        writeCenterSizeToText(statsFile2, centers)
        MVLength = tree.getTotalEdgeWeight()
        MVCost = MVLength * MV
        numTransformer = len(centers)

        try:
            netID =  tree.getNetID([*centers.values()][0])
        except:
            netID = 0
            tree._nodesByNetID[0] = []
            tree._network[netID] = []
        my_lv = 0
        connected_nodes = [len(nodesByClusterID[k]) for k in centers.keys()]

        # finding the revenue,

        demand = 0

        for k in centers.keys():

            #import ipdb; ipdb.set_trace()

            # selecting the nodes for that particular transformer
            selectedNodes = nodesByClusterID[k]

            # getting demands of each of them
            for i in selectedNodes:
                demand =  demand + i.getDemand()

        revenue = demand*cost_per_kwh*12



        #import ipdb; ipdb.set_trace()

        connected_nodes = sum(connected_nodes)

  

        for ID in centers.keys():
            nodesByNodeID = {}
            segments, lvCost = CMST_dfs_OLD.CMST(nodesByClusterID[ID], maxLVLenghtInCluster, centers[ID])
            my_lv += lvCost
            for segment in segments.values():
                node1 = segment.getNode1()
                node2 = segment.getNode2()
                if node1.getID() not in nodesByNodeID.keys():
                    nodesByNodeID[node1.getID()] = node1
                if node2.getID() not in nodesByNodeID.keys():
                    nodesByNodeID[node2.getID()] = node2

            for node in nodesByNodeID.values():
                tree._netIDByNode[node] = netID
                tree._nodesByNetID[netID].append(node)

            for segment in segments.values():
                tree._network[netID].append(segment)

        fileRW.genShapefile(tree, outputDir + ".prj", outputDir + os.sep + "FinalGrid.shp")


        with open(outputDir + 'modelOutput.txt', 'w') as dst:
            #dst.write("NumStructures:" + str(len(nodes)) + "\n")
            dst.write("NumConnectedStructures:" + str(connected_nodes) + "\n")
            #dst.write("LVLength:" + str(my_lv) + "\n")
            dst.write("LVPerCustomer:" + str(float(my_lv) / connected_nodes) + "\n")
            #dst.write("MVLength:" + str(MVLength) + "\n")
            dst.write("MVPerCustomer:" + str(MVLength / connected_nodes) + "\n")
            #dst.write("Num Transformers:" + str(numTransformer) + "\n")
            dst.write("Customers Per Tx:" + str(connected_nodes / float(numTransformer)) + "\n")
            #dst.write("Total LV Cost:" + str(my_lv * float(LV)) + "\n")
            #dst.write("Total MV Cost:" + str(MVCost) + "\n")
            transformerCost = numTransformer * TCost
            #dst.write("Transformer Cost:" + str(transformerCost) + "\n")
            total_cost = MVCost + my_lv * float(LV) + transformerCost
            #dst.write("Total Grid Cost:" + str(total_cost) + "\n")
            dst.write("GridCostPerCustomer:" + str(total_cost/ connected_nodes) + "\n")
            # dst.write("Offgrid Cost:" + str(offgrid_cost*(len(nodes)-connected_nodes)) + "\n")
            runningT = time.time() - startTime
            #dst.write("Total Running Time:" + str(runningT) + "\n")
            runningT1 = time.time() - startTime
            #dst.write("Final Running Time:" + str(runningT1) + "\n")
            dst.write("Total demand:" + str(demand) + "\n")
            dst.write("Revenue per year:" + str(revenue) + "\n")
     

                        #dst.write("NumStructures:" + str(len(nodes)) + "\n")
            print("NumConnectedStructures:" + str(connected_nodes) + "\n")
            #dst.write("LVLength:" + str(my_lv) + "\n")
            print("LVPerCustomer:" + str(float(my_lv) / connected_nodes) + "\n")
            #dst.write("MVLength:" + str(MVLength) + "\n")
            print("MVPerCustomer:" + str(MVLength / connected_nodes) + "\n")
            #dst.write("Num Transformers:" + str(numTransformer) + "\n")
            print("Customers Per Tx:" + str(connected_nodes / float(numTransformer)) + "\n")
            #dst.write("Total LV Cost:" + str(my_lv * float(LV)) + "\n")
            #dst.write("Total MV Cost:" + str(MVCost) + "\n")
            transformerCost = numTransformer * TCost
            #dst.write("Transformer Cost:" + str(transformerCost) + "\n")
            total_cost = MVCost + my_lv * float(LV) + transformerCost
            #dst.write("Total Grid Cost:" + str(total_cost) + "\n")
            print("GridCostPerCustomer:" + str(total_cost/ connected_nodes) + "\n")
            # dst.write("Offgrid Cost:" + str(offgrid_cost*(len(nodes)-connected_nodes)) + "\n")
            runningT = time.time() - startTime
            #dst.write("Total Running Time:" + str(runningT) + "\n")
            runningT1 = time.time() - startTime
            #dst.write("Final Running Time:" + str(runningT1) + "\n")
            print("Total demand:" + str(demand) + "\n")
            print("Revenue per year:" + str(revenue) + "\n")
      
        # with open(outputDir + 'modelOutput.txt', 'w') as dst:
        #     dst.write("NumStructures:" + str(len(nodes)) + "\n")
        #     dst.write("LVLength:" + str(my_lv) + "\n")
        #     dst.write("LVPerCustomer:" + str(float(my_lv) / len(nodes)) + "\n")
        #     dst.write("MVLength:" + str(MVLength) + "\n")
        #     dst.write("MVPerCustomer:" + str(MVLength / len(nodes)) + "\n")
        #     dst.write("Num Transformers:" + str(numTransformer) + "\n")
        #     dst.write("Customers Per Tx:" + str(len(nodes) / float(numTransformer)) + "\n")
        #     dst.write("Total LV Cost:" + str(my_lv * float(LV)) + "\n")
        #     dst.write("Total MV Cost:" + str(MVCost) + "\n")
        #     transformerCost = numTransformer * TCost
        #     dst.write("Transformer Cost:" + str(transformerCost) + "\n")
        #     total_cost = MVCost + my_lv * float(LV) + transformerCost
        #     dst.write("Total Cost:" + str(total_cost) + "\n")
        #     runningT = time.time() - startTime
        #     dst.write("Total Running Time:" + str(runningT) + "\n")
        #     # with open(outputDir+'modelOutput.txt', 'a') as dst:
        #     runningT1 = time.time() - startTime
        #     dst.write("Final Running Time:" + str(runningT1))
    except Exception as error_with_grid:
        print("Error with file:", error_with_grid)


if __name__ == "__main__":

    # my_file = '../../yuezi/polygonized_cambildge_preds_min_5ha.csv'
    # my_shp = '../../yuezi/polygonized_cambildge_preds_min_5ha/polygonized_cambildge_preds_min_5ha.shp'
    my_shp = '../shape-files/SoyNorth/subgrid_2.shp'
    # convert_to_utm_shp(my_file,my_shp,'epsg:32637')
    main(my_shp)
