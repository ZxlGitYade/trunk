#authors: katia.boschi@polimi.it, bruno.chareyre@3sr-grenoble.fr

# This script and features used in it are experimental. PLease wait stabilization before asking questions about it.

from yade import pack
from yade import export
from yade import timing
from yade import plot
import time
from math import *

num_spheres=1000# number of spheres
young=1.e6
compFricDegree = 3 # initial contact friction during the confining phase
finalFricDegree = 30 # contact friction during the deviatoric loading
mn,mx=Vector3(0,0,0),Vector3(1.,1.,0.4) # corners of the initial packing
graindensity=2600
errors=0
toleranceWarning =1.e-11
toleranceCritical=1.e-6

O.materials.append(FrictMat(young=young,poisson=0.5,frictionAngle=radians(compFricDegree),density=graindensity,label='spheres'))
O.materials.append(FrictMat(young=young,poisson=0.5,frictionAngle=0,density=0,label='walls'))
walls=aabbWalls([mn,mx],thickness=0,material='walls')
wallIds=O.bodies.append(walls)

sp=pack.SpherePack()
sp.makeCloud(mn,mx,-1,0.3333,num_spheres,False, 0.95,seed=1) #"seed" make the "random" generation always the same
sp.toSimulation(material='spheres')

triax=TriaxialStressController(
	maxMultiplier=1.+2e4/young, # spheres growing factor (fast growth)
	finalMaxMultiplier=1.+2e3/young, # spheres growing factor (slow growth)
	thickness = 0,
	stressMask = 7,
	max_vel = 0.005,
	internalCompaction=True, # If true the confining pressure is generated by growing particles
)

newton=NewtonIntegrator(damping=0.2)

O.engines=[
	ForceResetter(),
	InsertionSortCollider([Bo1_Sphere_Aabb(),Bo1_Box_Aabb()]),
	InteractionLoop(
		[Ig2_Sphere_Sphere_ScGeom(),Ig2_Box_Sphere_ScGeom()],
		[Ip2_FrictMat_FrictMat_FrictPhys()],
		[Law2_ScGeom_FrictPhys_CundallStrack()],label="iloop"
	),
	TwoPhaseFlowEngine(dead=1,label="flow"),#introduced as a dead engine for the moment, see 2nd section
	GlobalStiffnessTimeStepper(active=1,timeStepUpdateInterval=100,timestepSafetyCoefficient=0.8),
	triax,
	newton
]

triax.goal1=triax.goal2=triax.goal3=-10000

while 1:
	O.run(1000, True)
	unb=unbalancedForce()
	if unb<0.001 and abs(-10000-triax.meanStress)/10000<0.001:
		break

setContactFriction(radians(finalFricDegree))

radius=0
for b in O.bodies:
	if b.state.mass==0:
		b.state.blockedDOFs='xyzXYZ'
		b.state.vel=(0,0,0)
		b.state.angVel=(0,0,0)
	if b.state.mass>0:
		radius+=b.shape.radius
		#b.state.blockedDOFs='xyz'
		#b.state.vel=(0,0,0)
radius=radius/num_spheres

triax.dead=True
while 1:
	O.run(1000, True)
	unb=unbalancedForce()
	if unb<0.001:
		break

press=1000.    
O.run(10,1)

flow.dead=0
flow.meshUpdateInterval=-1
flow.useSolver=3
flow.permeabilityFactor=1
flow.viscosity=0.1

flow.bndCondIsWaterReservoir=[0,0,1,0,0,0]

flow.bndCondIsPressure=[0,0,1,0,0,0]
flow.bndCondValue=[0,0,press,0,0,0]
flow.boundaryUseMaxMin=[0,0,0,0,0,0]
flow.iniVoidVolumes=True
GlobalStiffnessTimeStepper.dead=True
O.dt=min(0.8*PWaveTimeStep(),0.8*1./1200.*pi/flow.viscosity*graindensity*radius**2)
O.dynDt=False
newton.damping=0.1

flow.surfaceTension = 0.0
flow.drainageFirst=False
flow.isDrainageActivated=False
flow.isImbibitionActivated=True
flow.isCellLabelActivated=True
flow.initialization()
cs=flow.getClusters()
c0=cs[1] 

voidvol=0.0
voidvoltot=0.0
nvoids=flow.nCells()
initialvol=[0.0] * (nvoids)
bar=[0.0] * (nvoids)
initiallevel=O.bodies[flow.wallIds[flow.ymin]].state.pos[1]+(O.bodies[flow.wallIds[flow.ymax]].state.pos[1]-O.bodies[flow.wallIds[flow.ymin]].state.pos[1])/3

for ii in range(nvoids):
	initialvol[ii]=1./flow.getCellInvVoidVolume(ii)
	voidvoltot+=initialvol[ii]
	bar[ii]=flow.getCellBarycenter(ii)[1]

iniok=0
while (iniok==0):
	celleini1=[nvoids+1] * (nvoids)
	celleini0=[0] * (nvoids)
	for ii in range(len(c0.getInterfaces())):
		if bar[c0.getInterfaces()[ii][1]]<initiallevel:
			if celleini1[c0.getInterfaces()[ii][1]]==nvoids+1:
				celleini1[c0.getInterfaces()[ii][1]]=ii
				celleini0[c0.getInterfaces()[ii][1]]=c0.getInterfaces()[ii][0]
	for ii in range(nvoids):
		if celleini1[ii]!=nvoids+1:
			flow.clusterOutvadePore(celleini0[ii],ii)
	no=0
	for ii in range(nvoids):
		if bar[ii]<initiallevel:
			if flow.getCellLabel(ii)==0:
				no=1
	if no==0:
		iniok=1
		for ii in range(len(c0.getInterfaces())):
			c0.setCapVol(ii,0.0)

c0.solvePressure()
flow.computeCapillaryForce(addForces=True,permanently=False)
O.run(1,1)
newton.dead=True
flow.savePhaseVtk("./vtk",True)

timeini=O.time 
ini=O.iter

Qin=0.0
#Qout=0.0

totalflux=[0.0] * (nvoids)
#totalCellSat=0.0

for ii in range(nvoids):
	if flow.getCellLabel(ii)==0:
		voidvol+=initialvol[ii]

bubble=0
dd=0.0   
deltabubble=0
col0=[0] * (nvoids)
neighK=[0.0] * (nvoids)

ints=c0.getInterfaces() #current interfaces
unsatPores=[]  #short list of pores with incoming fluxes
invadedPores=[] #pores invaded in current step
incidentInterfaces=[[] for i in range(nvoids)] # map interfaces connected to an interfacial (dry) pore

def updateInterfaces():
	ints=c0.getInterfaces() #current interfaces
	unsatPores=[]  #short list of pores with incoming fluxes
	incidentInterfaces=[[] for i in range(nvoids)]
	for idx in range(len(ints)):
		intf = ints[idx]
		if len(incidentInterfaces[intf[1]])==0: unsatPores.append(intf[1])
		incidentInterfaces[intf[1]].append(idx)

def pressureImbibition():
	global Qin,total2,dd,deltabubble,bubble,unsatPores,incidentInterfaces,invadedPores,ints

	start=time.time()

	c0.updateCapVolList(O.dt)
       
	Qin+=-1*(flow.getBoundaryFlux(flow.wallIds[flow.ymin]))*O.dt
	#Qout+=(flow.getBoundaryFlux(flow.wallIds[flow.ymax]))*O.dt   
   
	#print "1",time.time()-start
	#start=time.time()
   
	delta=[0.0] * (nvoids)   
	ints=c0.getInterfaces()

	if len(unsatPores)==0 or len(invadedPores)>0: #if not initialized or needs update
		# reset all lists if invasion occured in previous iterations
		# TODO: could be more atomic if they were updated after each local invasion
		unsatPores=[]
		invadedPores=[]
		incidentInterfaces=[[] for i in range(nvoids)]
		for idx in range(len(ints)):
			intf = ints[idx]
			if len(incidentInterfaces[intf[1]])==0:
				unsatPores.append(intf[1])
			incidentInterfaces[intf[1]].append(idx)
        
	for ii in unsatPores:
		totalflux[ii]=0.0
		for intf in incidentInterfaces[ii]:
			totalflux[ii]+=c0.getCapVol(intf)
		if (totalflux[ii])>=initialvol[ii]:
			invadedPores.append(ii) #more efficient later than looping on nvoids to check ==1
			delta[ii]=totalflux[ii]-initialvol[ii]
			totalflux[ii]=initialvol[ii]
			intf = incidentInterfaces[ii][0]
			col0[ii]=ints[intf][0]
	#if len(invadedPores)>0: print( "## invasion ##",len(invadedPores))
                    
	#print "2",time.time()-start
	#start=time.time()
   
	for jj in invadedPores:
		flow.clusterOutvadePore(col0[jj],jj)     
   
	#print "4",time.time()-start
	#start=time.time()
   
	if len(invadedPores)>0:
		#updateInterfaces() #redefine interfaces if outvade() changed them
		ints=c0.getInterfaces()
		for ll in invadedPores:
			if delta[ll]!=0.0:
				adjacentIds=flow.getNeighbors(ll,True)
				for n in range(len(adjacentIds)):
					if flow.getCellLabel(adjacentIds[n])==0:
						neighK[ll]+=flow.getConductivity(ll,n)
				if neighK[ll]==0.0:
					deltabubble+=delta[ll]
					bubble+=1
		for idx in range(len(ints)):
			ll=ints[idx][0]
			if delta[ll]!=0.0:
				if neighK[ll]!=0.0:					
					c0.setCapVol(idx,delta[ll]/neighK[ll]*c0.getConductivity(idx))
					totalflux[ints[idx][1]]+=delta[ll]/neighK[ll]*c0.getConductivity(idx)  

	#print "7",time.time()-start
	#start=time.time()
   
	if len(invadedPores)>0:
		# TODO: could be more atomic if they were updated after each local invasion
		unsatPores=[]
		invadedPores=[]
		incidentInterfaces=[[] for i in range(nvoids)]
		for idx in range(len(ints)):
			intf = ints[idx]
			if len(incidentInterfaces[intf[1]])==0:
				unsatPores.append(intf[1])
			incidentInterfaces[intf[1]].append(idx)
		for ii in unsatPores:
			if (totalflux[ii])>=initialvol[ii]:
				invadedPores.append(ii) #more efficient later than looping on nvoids to check ==1
				delta[ii]=totalflux[ii]-initialvol[ii]
				totalflux[ii]=initialvol[ii]
				intf = incidentInterfaces[ii][0]
				col0[ii]=ints[intf][0]
		for jj in invadedPores:
			flow.clusterOutvadePore(col0[jj],jj)
		if len(invadedPores)>0:
			#updateInterfaces() #redefine interfaces if outvade() changed them
			ints=c0.getInterfaces()
			for ll in invadedPores:
				if delta[ll]!=0.0:
					adjacentIds=flow.getNeighbors(ll,True)
					for n in range(len(adjacentIds)):
						if flow.getCellLabel(adjacentIds[n])==0:
							neighK[ll]+=flow.getConductivity(ll,n)
					if neighK[ll]==0.0:
						deltabubble+=delta[ll]
						bubble+=1
			for idx in range(len(ints)):
				ll=ints[idx][0]
				if delta[ll]!=0.0:
					if neighK[ll]!=0.0:					
						c0.setCapVol(idx,delta[ll]/neighK[ll]*c0.getConductivity(idx))
						totalflux[ints[idx][1]]+=delta[ll]/neighK[ll]*c0.getConductivity(idx)
			unsatPores=[]
			invadedPores=[]
			incidentInterfaces=[[] for i in range(nvoids)]
			for idx in range(len(ints)):
				intf = ints[idx]
				if len(incidentInterfaces[intf[1]])==0:
					unsatPores.append(intf[1])
				incidentInterfaces[intf[1]].append(idx)
			for ii in unsatPores:
				if (totalflux[ii])>=initialvol[ii]:
					invadedPores.append(ii) #more efficient later than looping on nvoids to check ==1
					delta[ii]=totalflux[ii]-initialvol[ii]
					totalflux[ii]=initialvol[ii]
					intf = incidentInterfaces[ii][0]
					col0[ii]=ints[intf][0]
					dd+=delta[ii]
					print (O.iter,"waterloss",ii,delta[ii])
			for jj in invadedPores:
				flow.clusterOutvadePore(col0[jj],jj)

	#print "8",time.time()-start
	#start=time.time

	total2=0.0
	for ii in range(nvoids):
		total2+=totalflux[ii]
	#print "9",time.time()-start
	#start=time.time()
	start=time.time()   
	c0.solvePressure()
	#print("10",time.time()-start)
	#start=time.time() 
	flow.computeCapillaryForce(addForces=True,permanently=False)
	#print( "11",time.time()-start)
	#start=time.time() 
	#not needed with new version of computeCapillaryForce()
	#for b in O.bodies:
	#O.forces.setPermF(b.id, flow.fluidForce(b.id))
	#print( "12",time.time()-start)


file=open('Test.txt',"w")
checkdifference=0
def equilibriumtest():
	global F33,F22,checkdifference,errors
	#unbalanced=utils.unbalancedForce()
	F33=abs(O.forces.f(flow.wallIds[flow.ymax])[1])
	F22=abs(O.forces.f(flow.wallIds[flow.ymin])[1])
	#F11 =abs(O.forces.f(flow.wallIds[flow.xmax])[0]),
	#F00=abs(O.forces.f(flow.wallIds[flow.xmin])[0]),
	#F44=abs(O.forces.f(flow.wallIds[flow.zmin])[2]),
	#F55=abs(O.forces.f(flow.wallIds[flow.zmax])[2]),
	deltaF=abs(F33-F22)
	file.write(str(O.iter)+" "+str(F33)+" "+str(F22)+" "+str(deltaF)+"\n")
	if O.time>=timeini+2.0:
		if checkdifference==0:
			print( 'check F done')
			if deltaF>0.01*press:
				print( 'Error: too high difference between forces acting at the bottom and upper walls')
				errors+=1
				#O.pause()
			checkdifference=1
 
once=0
def fluxtest():  
	global once,errors,QinOk
	no=0
   
	QinOk=Qin-deltabubble
	error=QinOk-total2
	if error>toleranceWarning:
		print( "Warning: difference between total water volume flowing through bottom wall and water loss due to air bubble generations",QinOk," vs. total water volume flowing inside dry or partially saturated cells",total2)
	if error>toleranceCritical:
		print("The difference is more, than the critical tolerance!")
		errors+=1         
	file.write(str(O.time-timeini)+" "+str(total2)+" "+str(QinOk)+" "+str(error)+"\n") 
   
	for ii in range(nvoids):
		if flow.getCellLabel(ii)==0:
			no=1
	if once==0:
		if no==0:
			imbtime=O.time-timeini
			print( imbtime,voidvol,total2,QinOk)
			if voidvol-total2>toleranceWarning:
				print( "Warning: initial volume of dry voids",voidvol," vs. total water volume flowing inside dry or partially saturated cells",total2)
			if voidvol-total2>toleranceCritical:
				print( "The difference is more, than the critical tolerance!")
				errors+=1
			print( errors)
			file.write(str(imbtime)+" "+str(voidvol)+" "+str(total2)+" "+str(QinOk)+" "+str(errors)+"\n") 
			once=1
			timing.stats()
			if (errors):
				resultStatus+=1
   

def addPlotData():
	plot.addData(i1=O.iter,
		t=O.time,
		Fupper=F33,
		Fbottom=F22,
		Q=QinOk,
		T=total2
	)
plot.live=True
plot.plots={' t ':('Fupper','Fbottom'),'t':('Q','T')} 
#plot.plot()
      

def pl():
	flow.savePhaseVtk("./vtk",True)

O.engines=O.engines+[PyRunner(iterPeriod=100,command='pl()')]
#O.engines=O.engines+[VTKRecorder(iterPeriod=100,recorders=['spheres'],fileName='./exp')]
O.engines=O.engines+[PyRunner(iterPeriod=1,command='pressureImbibition()')]
O.engines=O.engines+[PyRunner(iterPeriod=1,command='equilibriumtest()')]
O.engines=O.engines+[PyRunner(iterPeriod=1,command='fluxtest()')]
O.engines=O.engines+[PyRunner(iterPeriod=1,command='addPlotData()')]
O.engines=O.engines+[NewtonIntegrator(damping=0.1)]

O.timingEnabled=True
#O.run(100,True)
#timing.stats()

#file.close()
#plot.saveDataTxt('plots.txt',vars=('i1','t','Fupper','Fbottom','Q','T'))

#O.run(1,1)
