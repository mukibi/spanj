#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root);
my %session;
my $logd_in = 0;
my $id;
my $full_user = 0;

my $roll = undef;
my @esr_classes = ();
my $post_mode = 0;
my $act = undef;
my $update_session = 0;
my $conf_code = undef;

if ( exists $ENV{"QUERY_STRING"} ) {
	if ( $ENV{"QUERY_STRING"} =~ /\&?roll=([^\&]+)\&?/ ) {	
		$roll = $1;
	}
	if ( $ENV{"QUERY_STRING"} =~ /\&?act=([^\&]+)\&?/ ) {
		$act = $1;
	}
}
	
if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}
	#logged in 
	if (exists $session{"id"}) {	
		$id = $session{"id"};
		#privileges set
		if (exists $session{"privileges"}) {
			my $priv_str = $session{"privileges"};
			my $spc = " ";
			$priv_str =~ s/\+/$spc/g;
			$priv_str =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			if ($priv_str eq "all") { 
				$logd_in++;
				$full_user++;
			}
			else {
				if (exists $session{"token_expiry"} and $session{"token_expiry"} =~ /^\d+$/) {
					if ($session{"token_expiry"} > time) {
						$logd_in++;
						my @privs = split/,/,$priv_str;
						my $cntr = 0;
						foreach (@privs) {	
							if ($_ =~ m!^ESR\(([^\)]+)\)$!) {	
								push @esr_classes, $1;
							}
						}
					}
				}
			}
		}
	}
}

unless ($logd_in) {
	print "Status: 302 Moved Temporarily\r\n";
	print "Location: /login.html?cont=/cgi-bin/editroll.cgi\r\n";
	print "Content-Type: text/html; charset=UTF-8\r\n";
   	my $res = 
               	"<html>
               	<head>
		<title>Spanj: Exam Management Information System - Redirect Failed</title>
		</head>
         	<body>
                You should have been redirected to <a href=\"/login.html?cont=/cgi-bin/editroll.cgi\">/login.html?cont=/cgi-bin/editroll.cgi</a>. If you were not, <a href=\"/cgi-bin/editroll.cgi\">Click Here</a> 
		</body>
                </html>";

	my $content_len = length($res);	
	print "Content-Length: $content_len\r\n";
	print "\r\n";
	print $res;
	exit 0;
}
my %auth_params;
my %errors = ();
my %successful_image_writes;
my $con;
my %authd_adms;

my $current_yr = (localtime)[5] + 1900;
my %all_rolls;

my $yrs_of_study = 4;
my $house_label = "House/Dorm";

if (@esr_classes or $full_user) {
	#simply loads the entire stud rolls table to memory
	#and processes it from there
	#preferred over DB-side proc'ng because even with 
	#DB-side proc'ng, there wld still be complex
	#web-server side proc'ng
	unless ($con) {
		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	
	}
	if ($con) {
		my $prep_stmt = $con->prepare("SELECT table_name,class,start_year,grad_year,size FROM student_rolls");
		if ($prep_stmt) {
			my $rc = $prep_stmt->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt->fetchrow_array()) {
					my $yr = ($current_yr - $rslts[2]) + 1;
					
					my $class = $rslts[1];
					$class =~ s/\d+/$yr/;

					$all_rolls{$rslts[0]} = {"class" => $class, "start_year" => $rslts[2], "grad_year" => $rslts[3], "size" => $rslts[4]};
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM student_rolls: ", $prep_stmt->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM student_rolls: ", $prep_stmt->errstr, $/;  
		}

		my $prep_stmt2 = $con->prepare("SELECT id,value FROM vars WHERE id='1-classes' OR id='1-house label' LIMIT 2");
		if ($prep_stmt2) {
			my $rc = $prep_stmt2->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt2->fetchrow_array()) {

					if ($rslts[0] eq "1-classes") {

						my @classes = split/,/,$rslts[1];
						my ($min,$max);
						for my $class (@classes) {
							my $yr = undef;
							if ($class =~ /(\d+)/) {
								$yr = $1;
							}
					
							next if (not defined $yr);

							if (not defined $min) {
								$min = $yr;
								$max = $yr;
							}
							elsif ($yr < $min) {
								$min = $yr;
							}
							elsif ($yr > $max) {
								$max = $yr;
							}
						}

						$yrs_of_study = ($max - $min) + 1;
					}
					elsif ($rslts[0] eq "1-house label") {
						if (defined $rslts[1]) {
							$house_label = htmlspecialchars($rslts[1]);
						}
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM vars: ", $prep_stmt2->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM vars: ", $prep_stmt2->errstr, $/;  
		}
	}
	else {
		print STDERR "Cannot connect: $con->strerr$/";
	}
}

my %authd_rolls;

if ($full_user) {
	%authd_rolls = %all_rolls;
	for my $authd_table (keys %authd_rolls) {	
		my %roll_k_vs = %{$authd_rolls{$authd_table}};	
		my $class = $roll_k_vs{"class"};
		my $class_yr = ($current_yr - $roll_k_vs{"start_year"}) + 1;

		if ($class_yr > $yrs_of_study) {
			$class_yr = $yrs_of_study;
		}

		$class =~ s/\d+/$class_yr/;
		$roll_k_vs{"class"} = $class;
		$authd_rolls{$authd_table} = \%roll_k_vs; 
	}
}
else {
	#there might be a simpler way to do this
	#if she has been born, I'd love to meet her
	for my $esr_class (@esr_classes) {
		my $esr_stream = $esr_class;
		my $esr_start_year = $current_yr;
		if ($esr_stream =~ /(\d+)/) {
			my $esr_yr = $1;
			$esr_start_year -= ($esr_yr - 1) ;	
		}
		$esr_stream =~ s/\d+//g;
		J: for my $t_name (keys %all_rolls) {	
			my %roll_kv = %{$all_rolls{$t_name}};
			my $roll_stream = $roll_kv{"class"};
			$roll_stream =~ s/\d+//g;
			if (lc($esr_stream) eq lc($roll_stream)) {
				if ($roll_kv{"start_year"} == $esr_start_year) {
					$roll_kv{"class"} = $esr_class;
					$authd_rolls{$t_name} = \%roll_kv;
					last J;
				}
			}
		}
	}
}

#don't bother to connect to DB
#unless the user has some ESR privs

if ( defined $roll and defined $act and  ($act eq "edit" or $act eq "delete" or $act eq "add" or $act eq "move") ) {
	$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	
	if ($con) {
		my @where_clause_bts = ();
		foreach (keys %authd_rolls) {
			push @where_clause_bts, "table_name=?";
		}

		my $where_clause = join(" OR ", @where_clause_bts);
		
		my $prep_stmt10 = $con->prepare("SELECT adm_no FROM adms WHERE $where_clause");
		if ($prep_stmt10) {
			my $rc = $prep_stmt10->execute(keys %authd_rolls);
			if ($rc) {
				while (my @rslts = $prep_stmt10->fetchrow_array()) {
					$authd_adms{$rslts[0]}++; 
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM adms: ", $prep_stmt10->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM adms: ", $prep_stmt10->errstr, $/;  
		}
	}
	else {
		print STDERR "Cannot connect: $con->strerr$/";
	}
}

my $default_line_sep = $/;

#my $valid_data_posted = 0;
if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	my $multi_part = 0;
	$post_mode = 1;
	my $boundary = undef;
	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}
	if ($multi_part) {	
		$/ = "\r\n";	
		my $stage = 0;
		my $current_form_var = undef;
		my $current_form_var_content = "";

		my $form_var = 0;
		my $file_var = 0;
		my $file_name = undef;
		my $file_id = undef;
		my $file_ext = undef;
		my $write = 0;
		my $fh = undef;
		my $dir_lock = undef;
		my $adm_no = undef;		
		my $chomped = undef;

		while (<STDIN>) {
			$chomped = chomp;	
			if ($_ =~ /$boundary/) {	
				if ($form_var) {
					if (defined $current_form_var) {
						$auth_params{$current_form_var} = $current_form_var_content;	
					}
					$current_form_var = undef;
					$current_form_var_content = "";
				}
				elsif ($file_var) {
					if (defined $fh) {
						close $fh;
						$fh = undef;
					}
					if (defined $dir_lock) {
						flock ($dir_lock, LOCK_UN);
                				close $dir_lock;
						$dir_lock = undef;
						$successful_image_writes{$adm_no}++;
					}	
				}
				$form_var = 0;
				$file_var = 0;
				$stage = 1;
				$write = 0;	
				next;
			}
			if ($write) {
				if ($form_var) {	
					$current_form_var_content .= $_;
				}
				elsif ($file_var) {
					#this was added because png headers have a CRLF
					#may be useful in as-yet undiscovered situations
					if (defined $chomped) {
						$_ .= $/;
					}	
					print $fh $_;
				}
				next;
			}	
			if ($stage == 1) {
				if ($_ =~ /^Content-Disposition:\s*form-data;\s*name="(\d+)-picture";\s*filename="([^\"]+)"/) {			
					my $form_cntr = $1;
					$file_name = $2;
					$file_var = 1;	
					#what the user submits is a class number
					#translate this to an adm number
					if (exists $auth_params{"$form_cntr-adm"} and $auth_params{"$form_cntr-adm"} =~ /^(\d+)$/) {
						$adm_no = $1;
					}
					else {
						$file_var = 0;
					}
					#To be sure that no new images are
					#added while this user is saving theirs  
					open ($dir_lock, ">>${doc_root}/images/mugshots/.dir_lock");
        				if ($dir_lock) {
                				flock ($dir_lock, LOCK_EX) or print STDERR "lock error on mugshots dir_lock: $!$/"; 
						opendir(my $mugshots_dir, "${doc_root}/images/mugshots/");	
						my @files = readdir($mugshots_dir);
						F: foreach (@files) {
							my $adm = "";
							if ($_ =~ /^(\d+)\./) {
								$adm = $1;
							}
							else {
								next;
							}
							#if this image is already saved, check
							#if the user has perms to change it
							if ($adm eq $adm_no) {
								unless (exists $authd_adms{$adm}) {
									$file_var = 0;
									unless (exists $errors{$adm}) {
										$errors{$adm} = [];
									}
									push @{$errors{$adm}}, "Not authorized to change the picture for admission number $adm_no";
								}
								last F;
							}
						}
						closedir $mugshots_dir;
					}
					$file_ext = "";
					my $dot = rindex($file_name, ".");
					if ($dot) {
						$file_ext = substr($file_name, $dot); 
					}
					#what self-respecting image format would prance around the
					#internet with no file extension to grace its behind? None!
					else {
						$file_var = 0;
					}	
					$file_id = $adm_no . $file_ext;
				}
				elsif ($_ =~ /^Content-Disposition:\s*form-data;\s*name="(.+)"$/) {
					$current_form_var = $1;
					$form_var = 1;
				}
				$stage = 2;
				next;
			}
			if ($stage == 2) {
				if ($form_var) {
					if ($_ =~ /^$/) {
						$write = 1;
					}
				}
				if ($file_var) {
					if ($_ =~ m!^Content-Type:\s*image/!) {	
						$stage = 3;
					}
					else {
						unless (exists $errors{$adm_no}) {
							$errors{$adm_no} = [];
						}
						push @{$errors{$adm_no}}, "The file uploaded is not of a recognized image format";
					}
				}
				next;
			}
			if ($stage == 3) {
				if ($_ =~ /^$/) {
					open ($fh, ">${doc_root}/images/mugshots/$file_id") or print STDERR "Could not open mugshot for writing:$!$/";	
					$write = 1;
				}
				next;
			}
		}
		$/ = $default_line_sep;
	}
	else {

		my $str = "";

		while (<STDIN>) {
               		$str .= $_;
       		}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;
		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
}

my $content = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/editroll.cgi">Edit Student Roll</a>
	<hr> 
};

my $num_authd_rolls = scalar(keys %authd_rolls);

if ($num_authd_rolls) {
	$conf_code = gen_token();
	$update_session++;
	if ($post_mode) {
		#is the user authorized to make changes to the selected roll?
		if (exists $authd_rolls{$roll}) {
			if (exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $session{"confirm_code"} eq $auth_params{"confirm_code"}) {
				#simply alter the 'size' record of this roll in the student_rolls table
				#then present the mod'd table for editing with display_for_editing() 
				if ($act eq "add") {
					my $num_adds = $auth_params{"num_adds"};
					if ($num_adds =~ /^\d+$/) {
						my $prep_stmt8 = $con->prepare("UPDATE student_rolls SET size=size+$num_adds WHERE table_name=? LIMIT 1");
						my $rc = $prep_stmt8->execute($roll);
						unless ($rc) {
							print STDERR "Could not update student_rolls: $rc->strerr\n";
						}
						$con->commit();
						${$authd_rolls{$roll}}{"size"} += $num_adds;
					}
					display_for_editing($roll);
				}
				elsif ($act eq "delete") {
					#studs_to_del may not be def-ined if no studs were selected for deletion
					my @del_list = ();
					my $studs_to_del = $auth_params{"studs_to_del"};
					my $reduce_by = $auth_params{"reduce_by"};
					unless ($reduce_by =~ /^\d+$/) {
						$reduce_by = 0;
					}
					my $lim = ${$authd_rolls{$roll}}{"size"};	
					if (defined $studs_to_del) {
						#user wants to dump the entire table
						if ($studs_to_del eq "*") {
							#SELECT which students you are deleting
							foreach (keys %authd_adms) {
								push @del_list, $_;
							}

							#DROP the table...
							my $prep_stmt1 = $con->prepare("DROP TABLE IF EXISTS `$roll`");
							my $rc = $prep_stmt1->execute();
							unless ($rc) {
								print STDERR "Could not drop table: ", $prep_stmt1->errstr, "\n";
							}

							#DELETE meta-data...
							my $prep_stmt2 = $con->prepare("DELETE FROM student_rolls WHERE table_name=? LIMIT 1");
							$rc = $prep_stmt2->execute($roll);
							unless ($rc) {
								print STDERR "Could not delete from student_rolls: ", $prep_stmt2->errstr, "\n";
							}

							#DELETE individual studs from the school roll.	
							my $prep_stmt3 = $con->prepare("DELETE FROM adms WHERE table_name=? LIMIT $lim");
							$rc = $prep_stmt3->execute($roll);
						
							unless ($rc) {
								print STDERR "Could not delete from adms: ", $prep_stmt3->errstr, "\n";
							}

							my $class = ${$authd_rolls{$roll}}{"class"} . ", Class of " . ${$authd_rolls{$roll}}{"grad_year"};

							#DROP marksheets
							#1.) What marksheets fit the bill
							my $prep_stmt4 = $con->prepare("SELECT table_name FROM marksheets WHERE roll=?");
							if ($prep_stmt4) {
								my @marksheets_to_del = ();
								$rc = $prep_stmt4->execute($roll);
								if ($rc) {	
									while (my @rslts = $prep_stmt4->fetchrow_array()) {
										push @marksheets_to_del, qq!`$rslts[0]`!;	
									}
									#2.) DROP those that fit the idiomatic bill in 1.) above
									my $table_list = join(", ", @marksheets_to_del);
								 	my $prep_stmt5 = $con->prepare("DROP TABLE IF EXISTS $table_list");
									
									if ($prep_stmt5) {
										$rc = $prep_stmt5->execute($roll);
										unless ($rc) {
											print STDERR "Could not execute DROP marksheet statement: ", $prep_stmt5->errstr(), "\n";
										}
									}
									else {
										print STDERR "Could not prepare DROP marksheet statement: ", $prep_stmt5->errstr(). "\n";
									}
								}
								else {
									print STDERR "Could not execute SELECT FROM marksheets statement: ", $prep_stmt4->errstr(), "\n";
								}
							}
							else {
								print STDERR "Could not prepare SELECT FROM marksheets statement: ", $prep_stmt4->errstr(), "\n";
							}
							my @today = localtime;	
							my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        						if ($log_f) {	
                						@today = localtime;	
								my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
								flock ($log_f, LOCK_EX) or print STDERR "Could not log delete student roll for $id due to flock error: $!$/"; 
								seek ($log_f, 0, SEEK_END);
		 						print $log_f "$id DELETE STUDENT ROLL ($class) $time\n";
								flock ($log_f, LOCK_UN);
                						close $log_f;
        						}
							else {
								print STDERR "Could not log delete student roll for $id: $!\n";
							}
							$con->commit();
							$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Edit Student Roll</title>
</head>
<body>
$header
<em>Student roll $class has been deleted!</em>
};

						}
						#user wants to delete selected students
						else {
							my @adms_to_del = split/,/, $studs_to_del;
							for (my $i = 0; $i < @adms_to_del; $i++) {
								unless ($adms_to_del[$i] =~ /^\d+$/) {
									$reduce_by--;
									splice(@adms_to_del, $i, 1);	
								}
								unless (exists $authd_adms{$adms_to_del[$i]}) {
									$reduce_by--;
									splice(@adms_to_del, $i, 1);	
								}
							}
							if (@adms_to_del) {
								@del_list = @adms_to_del;
								my $lim = scalar(@adms_to_del);
								my @where_clause_bts = ();
								foreach (@adms_to_del) {
									push @where_clause_bts, "adm=?";
								}
								my $where_clause = join (' OR ', @where_clause_bts);
								my $prep_stmt5 = $con->prepare("DELETE FROM `$roll` WHERE $where_clause LIMIT $lim");
								my $rc = $prep_stmt5->execute(@adms_to_del);
								unless ($rc) {
									print STDERR "Could not DELET FROM $roll: ", $prep_stmt5->errstr, "\n";
								}

								@where_clause_bts = ();
								foreach (@adms_to_del) {
									push @where_clause_bts, "adm_no=?";
								}
								$where_clause = join (' OR ', @where_clause_bts);
								my $prep_stmt6 = $con->prepare("DELETE FROM adms WHERE $where_clause LIMIT $lim");
								$rc = $prep_stmt6->execute(@adms_to_del);
								unless ($rc) {
									print STDERR "Could not delete from adms: $rc->strerr";
								}

								#delete from marksheets
								#1.) What marksheets fit the bill
								my $prep_stmt4 = $con->prepare("SELECT table_name FROM marksheets WHERE roll=?");
								if ($prep_stmt4) {
									my @marksheets_to_del = ();
									$rc = $prep_stmt4->execute($roll);
									if ($rc) {
										while (my @rslts = $prep_stmt4->fetchrow_array()) {
											push @marksheets_to_del, $rslts[0];	
										}
										#2.) DROP those that fit the idiomatic bill in 1.) above
										my $table_list = join(", ", @marksheets_to_del);
										for my $marksheet (@marksheets_to_del) {
											@where_clause_bts = ();	
											#multi-table deletes are ridiculous, FYI
											for my $adm (@adms_to_del) {	
												push @where_clause_bts, "adm=?";	
											}

											my $where_clause = join (' OR ', @where_clause_bts);
											my $lim = scalar(@adms_to_del);

										 	my $prep_stmt5 = $con->prepare("DELETE FROM `$marksheet` WHERE $where_clause LIMIT $lim");	
									
											if ($prep_stmt5) {
												$rc = $prep_stmt5->execute(@adms_to_del);
												unless ($rc) {
													print STDERR "Could not execute DELETE FROM marksheets statement: ", $prep_stmt5->errstr(), "\n";
												}
											}
											else {
												print STDERR "Could not prepare DELETE FROM marksheets statement: ", $prep_stmt5->errstr(), "\n";
											}
										}
									}
									else {
										print STDERR "Could not execute SELECT FROM marksheets statement: ", $prep_stmt4->errstr(), "\n";
									}
								}
								else {
									print STDERR "Could not prepare SELECT FROM marksheets statement: ", $prep_stmt4->errstr(), "\n";
								}
								
								my @today = localtime;	
								my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
								open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        							if ($log_f) {	
                							@today = localtime;	
									my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
									flock ($log_f, LOCK_EX) or print STDERR "Could not log student delete for $id due to flock error: $!$/"; 
									seek ($log_f, 0, SEEK_END);
									for my $adm (@adms_to_del) { 
		 								print $log_f "$id STUDENT DELETE $adm $time\n";
									}
									flock ($log_f, LOCK_UN);
                							close $log_f;
        							}
								else {
									print STDERR "Could not log student delete for $id: $!\n";
								}
							}
							if ($reduce_by) {
								my $prep_stmt7 = $con->prepare("UPDATE student_rolls SET size=size-$reduce_by WHERE table_name=? LIMIT 1");
								my $rc = $prep_stmt7->execute($roll);
								${$authd_rolls{$roll}}{"size"} -= $reduce_by; 
								unless ($rc) {
									print STDERR "Could not update student_rolls: $prep_stmt7->strerr\n";
								}
							}
							$con->commit();
							display_for_editing($roll);
						}
					}
					#delete images as well
					if (@del_list) {
						my %del_hash = ();
						foreach (@del_list) {
							$del_hash{$_}++;
						}	
						open (my $dir_lock, ">>${doc_root}/images/mugshots/.dir_lock");
        					if ($dir_lock) {
                					flock ($dir_lock, LOCK_EX) or print STDERR "lock error on mugshots dir_lock: $!$/"; 
							opendir(my $mugshots_dir, "${doc_root}/images/mugshots/");
							my @images = readdir($mugshots_dir);
							for my $image (@images) {
								if ($image =~ /^(\d+)\./) {
									my $adm = $1;
									if (exists $del_hash{$adm}) {
										unlink "${doc_root}/images/mugshots/$image" or print STDERR "Could not delete mugshot $image: $!";
									}
								}
							}
							closedir $mugshots_dir;
							flock ($dir_lock, LOCK_UN);
                					close $dir_lock;
						}
					}
				}
				#move between classes
				#simply:
				#1.) update the adms table
				#do a SELECT|UPDATE between the relevant tables
				elsif ($act eq "move") {	

					my $studs_to_move = $auth_params{"studs_to_move"};
					my @move_list = split/,/, $studs_to_move;

					for (my $i = 0; $i < @move_list; $i++) {
						unless ($move_list[$i] =~ /^\d+$/) {
							splice(@move_list, $i, 1);
						}
						unless (exists $authd_adms{$move_list[$i]}) {
							splice(@move_list, $i, 1);
						}
					}
	
					
					my $reduce_by = scalar(@move_list);

					if ($reduce_by) {

						#1.) Move between tables
						my $move_to = $auth_params{"move_to"};

						if ( exists $authd_rolls{$move_to} ) {

							my $move_to_classname = ${$all_rolls{$move_to}}{"class"};
							my @where_clause_bts = ();
							foreach (@move_list) {
								push @where_clause_bts, "adm=?";
							}
							my $where_clause = join(" OR ", @where_clause_bts);

							#Insert into new table from old table
							my $prep_stmt13 = $con->prepare("INSERT IGNORE INTO `$move_to` SELECT * FROM `$roll` WHERE $where_clause");
							my $rc = $prep_stmt13->execute(@move_list);

							unless ($rc) {
								print STDERR "Could not update $move_to: $prep_stmt13->strerr\n";
							}	

							#Delete from old table
							my $prep_stmt14 = $con->prepare("DELETE FROM `$roll` WHERE $where_clause LIMIT $reduce_by");
							$rc = $prep_stmt14->execute(@move_list);

							unless ($rc) {
								print STDERR "Could not delete from $roll: $prep_stmt14->strerr\n";
							}

							#2.) Update adms table	
							my @insert_vals = ();
							my @bind_vals = ();
							foreach (@move_list) {
								push @bind_vals, $_, $move_to;
								push @insert_vals, "(?, ?)";
							}

							my $insert_str = join(", ", @insert_vals);
	
							#insert new values into adms
							my $prep_stmt15 = $con->prepare("REPLACE INTO adms VALUES $insert_str");
							$rc = $prep_stmt15->execute(@bind_vals);

							unless ($rc) {
								print STDERR "Could not update adms table: $prep_stmt15->strerr\n";
							}


							#3.) Update student rolls size
							my $lim = ${$authd_rolls{$roll}}{"size"};
				
							my $prep_stmt7 = $con->prepare("UPDATE student_rolls SET size=size-? WHERE table_name=? LIMIT 1");
						
							#take away	
							$rc = $prep_stmt7->execute($reduce_by, $roll);
							#add to
							#matter must be conserved--I had forgotten this
							$rc = $prep_stmt7->execute(-1 * $reduce_by, $move_to);

							${$authd_rolls{$roll}}{"size"} -= $reduce_by; 
							unless ($rc) {
								print STDERR "Could not update student_rolls: $prep_stmt7->strerr\n";
							}

							my @today = localtime;	
							my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
							open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
       							if ($log_f) {	
               							@today = localtime;	
								my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
								flock ($log_f, LOCK_EX) or print STDERR "Could not log student delete for $id due to flock error: $!$/"; 
								seek ($log_f, 0, SEEK_END);
								for my $adm (@move_list) { 
	 								print $log_f "$id STUDENT MOVE $adm to $move_to_classname $time\n";
								}
								flock ($log_f, LOCK_UN);
               							close $log_f;
       							}
							else {
								print STDERR "Could not log student move for $id: $!\n";
							}
							$con->commit();
							display_for_editing($roll);
						}

						else {
							$errors{"Unauthorized"} = "You are not authorized to insert into the roll you selected to move the student into. Or the student roll does not exist.";
							display_for_editing($roll, 1);
						}
					}
					else {
						$errors{"Unauthorized"} = "You are not authorized to edit any of the admission numbers you selected. Alternatively, you sent invalid admission numbers.";
						display_for_editing($roll);
					}
				}

				elsif ($act eq "edit") {
					#check if this' an edit or addition
					#to do this, load every record
					#if addition, just INSERT INTO DB
					#log this as a STUDENT ADD (adm, s_name, o-names
					#if edit, check values that vary from saved
					#values
					#log this as STUDENT EDIT (adm, values changed)
					
					my $valid_subjects_str = 'English,Kiswahili,Mathematics,Chemistry,Physics,Biology,Geography,History and Government,Christian Religious Education,Computers,Business Studies,Agriculture,Art & Design';
					my $valid_dorms_str = '';
		
					my $prep_stmt12 = $con->prepare("SELECT id,value FROM vars WHERE id='1-subjects' OR id='1-dorms' LIMIT 2");
					if ($prep_stmt12) {
						my $rc = $prep_stmt12->execute();
						if ($rc) {
							while (my @rslts = $prep_stmt12->fetchrow_array()) {
								if ($rslts[0] eq "1-subjects") {
									$valid_subjects_str = $rslts[1];	
								}
								elsif ($rslts[0] eq "1-dorms") {
									$valid_dorms_str = $rslts[1];
								}
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM vars: ", $prep_stmt12->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM vars: ", $prep_stmt12->errstr, $/;  
					}

					my @subjects = split/,/,$valid_subjects_str;
					my %valid_subjects = ();
					foreach (@subjects) {
						$valid_subjects{$_}++;
					}
					my @dorms = split/,/,$valid_dorms_str;
					my %valid_dorms;
					foreach (@dorms) {
						$valid_dorms{uc($_)}++;
					}
				
					my %subjects_checked;
					my %clubs_selected;
					my %games_selected;

					my @altd_adms = ();
					my %cntr_adm_lookup;
					my %adm_cntr_lookup;

					for my $param (keys %auth_params) {

						if ($param =~ /(\d+)-adm/) {
							my $cntr = $1;
							my $adm = $auth_params{$param};
							#adms are smallint unsigned (0-65535)
							#God forbid that any schools should out-grow this
							#divine limit
							if ($adm =~ /^\d+$/) {
								if ($adm >= 0 and $adm < 65536) {
									$adm_cntr_lookup{$adm} = $cntr;
									$cntr_adm_lookup{$cntr} = $adm;	
								}
							}
						}
						elsif ($param =~ /^(\d+)-subject-/) {
							my $cntr = $1;
							unless (exists $subjects_checked{$cntr}) {
								$subjects_checked{$cntr} = [];
							}
							my $subject = $auth_params{$param};
							push @{$subjects_checked{$cntr}}, $subject;
						}
						
						elsif ($param =~ /^(\d+)-club/ or $param =~ /(\d+)-society/) {
							my $cntr = $1;
							unless (exists $clubs_selected{$cntr}) {
								$clubs_selected{$cntr} = [];
							}
							my $club = $auth_params{$param};
							unless ($club eq "") {
								push @{$clubs_selected{$cntr}}, $club;	
							}
						}

						elsif ($param =~ /^(\d+)-game/) {
							my $cntr = $1;
							unless (exists $games_selected{$cntr}) {
								$games_selected{$cntr} = [];
							}
							my $game = $auth_params{$param};
							unless ($game eq "") {
								push @{$games_selected{$cntr}}, $game;
							}
						}
					}

					my %stud_data;
 	
					my $prep_stmt11 = $con->prepare("SELECT adm,s_name,o_names,has_picture,marks_at_adm,subjects,clubs_societies,sports_games,responsibilities,house_dorm FROM `$roll`");
					if ($prep_stmt11) {
						my $rc = $prep_stmt11->execute();
						if ($rc) {
							while (my @rslts = $prep_stmt11->fetchrow_array()) {
								for (my $i = 0; $i < @rslts; $i++) {
									if (not defined($rslts[$i])) {
										$rslts[$i] = "";
									}
								}
								my ($adm,$s_name,$o_names,$has_picture,$marks_at_adm,$subjects,$clubs_societies,$games_sports,$responsibilities,$house_dorm) = @rslts;
								$stud_data{$adm} = {"s_name" => $s_name, "o_names" => $o_names, "has_picture" => $has_picture, "marks_at_adm" => $marks_at_adm, "subjects" => $subjects, "clubs_societies" => $clubs_societies, "games_sports" => $games_sports, "responsibilities" => $responsibilities, "house_dorm" => $house_dorm};	
							}
						}
						else {
							print STDERR "Could not execute SELECT FROM $roll: ", $prep_stmt11->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare SELECT FROM $roll: ", $prep_stmt11->errstr, $/;  
					}

					my @new_adms;
 
					foreach (keys %adm_cntr_lookup) {
						unless (exists $stud_data{$_}) {
							push @new_adms, $_; 
						}
					}

					#to avoid the menace of assigning multiple students the same
					#admission number...
					my %collision_adms = ();

					if (@new_adms) {
						my %collision_rolls;
						my @collision_where_clause_bts = ();

						foreach (@new_adms) {
							push @collision_where_clause_bts, "adm_no=?";
						}
						my $collision_where_clause = join(' OR ', @collision_where_clause_bts);
					
						my $prep_stmt_collision = $con->prepare("SELECT adm_no,table_name FROM adms WHERE $collision_where_clause");
						if ($prep_stmt_collision) {
				
							my $rc = $prep_stmt_collision->execute(@new_adms);
							if ($rc) {
								while (my @rslts = $prep_stmt_collision->fetchrow_array()) {
									$collision_adms{$rslts[0]} = $rslts[1];
									$collision_rolls{$rslts[1]}++;
								}
							}
							else {
								print STDERR "Could not execute() SELECT FROM adms: ", $prep_stmt_collision->errstr, "\n";
							}
						}
						else {
							print STDERR "Couldn't prepare SELECT FROM adms: ", $prep_stmt_collision->errstr, "\n";
						}

						#read the metadata for the class list from which the potential collisions are to be found
						my @collision_rolls_where_clause_bts = ();

						
						foreach (keys %collision_rolls) {
							push @collision_rolls_where_clause_bts, "table_name=?";
						}
						
						if (@collision_rolls_where_clause_bts) {
							my $collision_rolls_where_clause = join (' OR ', @collision_rolls_where_clause_bts);

							my $prep_stmt_collision_rolls = $con->prepare("SELECT table_name,class,start_year,grad_year FROM student_rolls WHERE $collision_rolls_where_clause");
							if ($prep_stmt_collision_rolls) {
				
								my $rc = $prep_stmt_collision_rolls->execute(keys %collision_rolls);
								if ($rc) {
									while (my @rslts = $prep_stmt_collision_rolls->fetchrow_array()) {
										my ($class_list,$class, $start, $grad) = @rslts;
										my $current_yr = (localtime)[5] + 1900;
										my $class_yr = ($current_yr - $start) + 1;
										$class =~ s/\d+/$class_yr/;
										$collision_rolls{$class_list} = "$class (Class of $grad)";
									}
								}
								else {
									print STDERR "Could not execute() SELECT FROM student_rolls: ", $prep_stmt_collision_rolls->errstr, "\n";
								}
							}
							else {
								print STDERR "Could not prepare SELECT FROM student_rolls: ", $prep_stmt_collision_rolls->errstr, "\n";
							}
						}

						foreach (keys %collision_adms) {
							my $class_lst = $collision_adms{$_};
							$collision_adms{$_} = $collision_rolls{$class_lst};
						}
					}
					my %edits;
					my %adds;

					for my $adm (keys %adm_cntr_lookup) {	
						my $cntr = $adm_cntr_lookup{$adm};
						my @new_vals;
						my @update_clause_bts;

						unless (exists $errors{$adm}) {
							$errors{$adm} = [];
						}
						#this change is an edit
						if (exists $stud_data{$adm}) {	
							my @changed;
							my %current_vars = %{$stud_data{$adm}};	
							#load each data element uploaded
							#compare it with the saved data
							#s_name
							if (exists $auth_params{$cntr . "-s_name"}) {
								my $new_s_name =  $auth_params{$cntr . "-s_name"};
								if ($new_s_name ne $current_vars{"s_name"}) {
									if (length($new_s_name) <= 16) {
										if ($new_s_name =~ /^[a-zA-Z'\s-]+$/) {	
											push @update_clause_bts, "s_name=?";
											push @changed, "Surname";
											push @new_vals, $new_s_name;
										}
										else {
											push @{$errors{$adm}}, "Invalid characters in the surname. Valid charcters are the alphabet and a few symbols (',-,spaces)";
										}
									}
									else {
										push @{$errors{$adm}}, "The surname given is too long. A valid surname should be 16 or fewer characters";	
									}
								}
							}
							#o_names
							if (exists $auth_params{$cntr . "-o_names"}) {
								my $new_o_names =  $auth_params{$cntr . "-o_names"};
								if ($new_o_names ne $current_vars{"o_names"}) {
									if (length($new_o_names) <= 64) {
										if ($new_o_names =~ /^[a-zA-Z'\s-]+$/) {	
											push @update_clause_bts, "o_names=?";
											push @changed, "Other names";
											push @new_vals, $new_o_names;
										}
										else {
											push @{$errors{$adm}}, "Invalid characters in the 'other names' field. Valid charcters are the alphabet and a few symbols (',-,spaces)";
										}
									}
									else {
										push @{$errors{$adm}}, "The 'other names' field is too long. It should be 64 or fewer characters";	
									}
								}
							}
							#picture
							if (exists $successful_image_writes{$adm}) {
								#only do a DB update if student was faceless previously
								if ($current_vars{"has_picture"} ne "yes") {
									push @update_clause_bts, "has_picture=?";
									push @new_vals, "yes";
								}
								#but always log a change of the picture
								push @changed, "Picture";
							}
							#marks at admission
							if (exists $auth_params{$cntr . "-marks_at_adm"}) {
								my $new_marks_at_adm = $auth_params{$cntr . "-marks_at_adm"};
								if ($new_marks_at_adm ne $current_vars{"marks_at_adm"}) { 
									if ($new_marks_at_adm =~ /^\d+$/ and $new_marks_at_adm >= 0 and $new_marks_at_adm < 65536) {
										push @update_clause_bts, "marks_at_adm=?";
										push @new_vals, $new_marks_at_adm;
										push @changed, "Marks at admission";
									}
									else {
										push @{$errors{$adm}}, "Invalid 'marks at admission' value. This value should be a number in the range 0-65535"
									}
								}
							}
							#subjects
							if (exists $subjects_checked{$cntr}) {
								my @new_subjects = @{$subjects_checked{$cntr}};
								my @old_subjects = split/,/, $current_vars{"subjects"};
								my $match = 1;
								#determining whether a change has occurred will often
								#be as simple as comparing the size of the old and new array
								if (scalar(@new_subjects) != scalar(@old_subjects)) {
									$match = 0;
								}
								else {
									my $matches = 0;
									OUT: for (my $i = 0; $i < @new_subjects; $i++) {
										unless (exists $valid_subjects{$new_subjects[$i]}) {
											push @{$errors{$adm}}, "Unknown subject. To add a new subject, ask the administrator to edit the 'subjects' system variable";
											next OUT; 
										}
										IN: for (my $j = 0; $j < @old_subjects; $j++) {
											if ($new_subjects[$i] eq $old_subjects[$j]) {
												$matches++;
												last IN;
											}
										}
									} 
									unless ($matches == scalar(@new_subjects)) {
										$match = 0;
									}
								}
								unless ($match) {
									my $subjs = join(",", @new_subjects);
									#subjects is internally a varchar(256)
									if (length($subjs) <= 256) {
										push @update_clause_bts, "subjects=?";
										push @new_vals, $subjs;
										push @changed, "Subjects";
									}
									else {
										push @{$errors{$adm}}, "Too many subjects were selected. Check to make sure no subjects were selected multiple times. If this issue persists, notify the developer.";
									}
								}
							}

							#clubs/societies
							if (exists $clubs_selected{$cntr}) {	
								my @new_clubs = @{$clubs_selected{$cntr}};	
								my @old_clubs = split/,/, $current_vars{"clubs_societies"};
								my $match = 1;
								#determining whether a change has occurred will often
								#be as simple as comparing the size of the old and new array
								if (scalar(@new_clubs) != scalar(@old_clubs)) {
									$match = 0;
								}
								else {
									my $matches = 0;
									for (my $i = 0; $i < @new_clubs; $i++) {
										IN2: for (my $j = 0; $j < @old_clubs; $j++) {
											if ($new_clubs[$i] eq $old_clubs[$j]) {
												$matches++;
												last IN2;
											}
										}
									} 
									unless ($matches == scalar(@new_clubs)) {
										$match = 0;
									}
								}
								unless ($match) {
									my $klubs = join(",", @new_clubs);
									#clubs_societies is internally a varchar(32)
									if (length($klubs) <= 80) {
										push @update_clause_bts, "clubs_societies=?";
										push @new_vals, $klubs;
										push @changed, "Clubs/Societies";
									}
									else {
										push @{$errors{$adm}}, "Too many clubs were selected. Check to make sure no clubs were selected multiple times. If you still get this error, notify the developer.";
									}
								}
							}

							#games/sports
							if (exists $games_selected{$cntr}) {
								my @new_games = @{$games_selected{$cntr}};
								my @old_games = split /,/, $current_vars{"games_sports"};
								my $match = 1;
								#determining whether a change has occurred will often
								#be as simple as comparing the size of the old and new array
								if (scalar(@new_games) != scalar(@old_games)) {
									$match = 0;
								}
								else {
									my $matches = 0;
									for (my $i = 0; $i < @new_games; $i++) {
										IN3: for (my $j = 0; $j < @old_games; $j++) {
											if ($new_games[$i] eq $old_games[$j]) {
												$matches++;
												last IN3;
											}
										}
									}
									unless ($matches == scalar(@new_games)) {
										$match = 0;
									}
								}
								unless ($match) {	
									my $gayms = join(",", @new_games);
									#games_sports is internally a varchar(48)
									if (length($gayms) <= 48)  {
										push @update_clause_bts, "sports_games=?";
										push @new_vals, $gayms;
										push @changed, "Sports/Games";
									}
									else {
										push @{$errors{$adm}}, "Too many games were selected. Check to make sure no games were selected multiple times. If you still get this error, notify the developer.";
									}
								}
							}
							#responsibilities
							if (exists $auth_params{$cntr . "-responsibilities"}) {
								my $new_respons = $auth_params{$cntr . "-responsibilities"};
								if ($new_respons ne $current_vars{"responsibilities"}) { 
									if ( length($new_respons) <= 48 ) { 
										push @update_clause_bts, "responsibilities=?";
										push @new_vals, $new_respons;
										push @changed, "Responsibilities";
									}
									else {
										push @{$errors{$adm}}, "Too many responsibilities were selected. Check to make sure no responsibilities were entered multiple times. If you still get this error, notify the developer.";	
									}
								}
							}
							#dorm
							if (exists $auth_params{$cntr . "-dorm"}) {
								my $new_dorm = $auth_params{$cntr . "-dorm"};
								if ($new_dorm ne $current_vars{"house_dorm"}) {
									if (exists $valid_dorms{uc($new_dorm)}) { 
										if ( length($new_dorm) <= 32 ) { 
											push @update_clause_bts, "house_dorm=?";
											push @new_vals, $new_dorm;
											push @changed, "House/Dorm";
										}
										else {
											push @{$errors{$adm}}, "The dorm name is too long. To fix this issue, ask the administrator to change its name by changing the 'dorms' variable.";
										}
									}
									else {
										push @{$errors{$adm}}, "The dorm entered is not one of those configured by the administrator. Valid dorms are: $valid_dorms_str. If you want to add this dorm to the list, ask the administrator to change the 'dorms' system variable.";
									}
								}
							}
							if (@new_vals) {
								push @new_vals, $adm;
								my $set_clause = join (',', @update_clause_bts);
								my $prep_stmt = $con->prepare("UPDATE `$roll` SET $set_clause WHERE adm=? LIMIT 1");	
								if ($prep_stmt) {
									my $rc = $prep_stmt->execute(@new_vals);
									unless ($rc) {
										print STDERR "Could not execute UPDATE $roll stmt: ", $prep_stmt->errstr, "\n";
									}
								}
								else {
									print STDERR "Could not prep UPDATE $roll stmt: ", $prep_stmt->errstr, "\n";
								}
								$edits{$adm} = \@changed;
							}
						}
						#this change is an addition
						else {	
							#detect collisions
							#lookup if this adm is in the %collision_adms hashtable
							if (exists $collision_adms{$adm}) {	
								my $cls = $collision_adms{$adm};
								push @{$errors{$adm}}, "The admission number '$adm' has been assigned to a student in $cls. This record will be ignored.";
							}
							else {
								my ($seen_s_name, $seen_o_names) = (0,0);
								#adm
								push @update_clause_bts, "adm=?";
								push @new_vals, $adm;
								#s_name
								if (exists $auth_params{$cntr . "-s_name"}) {
									my $new_s_name =  $auth_params{$cntr . "-s_name"};
						
									if (length($new_s_name) <= 16) {
										if ($new_s_name =~ /^[a-zA-Z'\s-]+$/) {	
											push @update_clause_bts, "s_name=?";	
											push @new_vals, $new_s_name;
											$seen_s_name++;
										}
										else {
											push @{$errors{$adm}}, "Invalid characters in the surname. Valid charcters are the alphabet and a few symbols (',-,spaces)";
										}
									}
									else {
										push @{$errors{$adm}}, "The surname given is too long. A valid surname should be 16 or fewer characters";	
									}
								}
								#o_names
								if (exists $auth_params{$cntr . "-o_names"}) {
									my $new_o_names =  $auth_params{$cntr . "-o_names"};
						
										if (length($new_o_names) <= 64) {
											if ($new_o_names =~ /^[a-zA-Z'\s-]+$/) {	
												push @update_clause_bts, "o_names=?";	
												push @new_vals, $new_o_names;
												$seen_o_names++;
											}
											else {
												push @{$errors{$adm}}, "Invalid characters in the 'other names' field. Valid charcters are the alphabet and a few symbols (',-,spaces)";
											}
										}
										else {
											push @{$errors{$adm}}, "The 'other names' field is too long. It should be 64 or fewer characters";	
										}
							
								}
								#picture
								if (exists $successful_image_writes{$adm}) {			
									push @update_clause_bts, "has_picture=?";
									push @new_vals, "yes";
								}
								#marks at admission
								if (exists $auth_params{$cntr . "-marks_at_adm"} and $auth_params{$cntr . "-marks_at_adm"} ne"") {
									my $new_marks_at_adm = $auth_params{$cntr . "-marks_at_adm"};
							
									if ($new_marks_at_adm =~ /^\d+$/ and $new_marks_at_adm >= 0 and $new_marks_at_adm < 65536) {
										push @update_clause_bts, "marks_at_adm=?";
										push @new_vals, $new_marks_at_adm;
										
									}
									else {
										push @{$errors{$adm}}, "Invalid 'marks at admission' value. This value should be a number in the range 0-65535"
									}
							
								}
								#subjects
								if (exists $subjects_checked{$cntr}) {
									my @new_subjects = @{$subjects_checked{$cntr}};
									
									for (my $i = 0; $i < @new_subjects; $i++) {
										unless (exists $valid_subjects{$new_subjects[$i]}) {
											push @{$errors{$adm}}, "Unknown subject. To add a new subject, ask the administrator to edit the 'subjects' system variable";
											splice (@new_subjects, $i, 1);
										}
									}
									if (@new_subjects) {		
										my $subjs = join(",", @new_subjects);
										#subjects is internally a varchar(256)
										if (length($subjs) <= 256) {
											push @update_clause_bts, "subjects=?";
											push @new_vals, $subjs;	
										}
										else {
											push @{$errors{$adm}}, "Too many subjects were selected. Check to make sure no subjects were selected multiple times. If this issue persists, notify the developer.";
										}
									}
								}

								#clubs/societies
								if (exists $clubs_selected{$cntr}) {	
									my @new_clubs = @{$clubs_selected{$cntr}};
									my $klubs = join(",", @new_clubs);
									#clubs_societies is internally a varchar(32)
									if (length($klubs) <= 80) {
										push @update_clause_bts, "clubs_societies=?";
										push @new_vals, $klubs;	
									}
									else {
										push @{$errors{$adm}}, "Too many clubs were selected. Check to make sure no clubs were selected multiple times. If you still get this error, notify the developer.";
									}
							
								}

								#games/sports
								if (exists $games_selected{$cntr}) {
									my @new_games = @{$games_selected{$cntr}};	
									my $gayms = join(",", @new_games);
									#games_sports is internally a varchar(48)
									if (length($gayms) <= 48) {
										push @update_clause_bts, "sports_games=?";
										push @new_vals, $gayms;	
									}
									else {
										push @{$errors{$adm}}, "Too many games were selected. Check to make sure no games were selected multiple times. If you still get this error, notify the developer.";
									}
								}
								#responsibilities
								if (exists $auth_params{$cntr . "-responsibilities"} and $auth_params{$cntr . "-responsibilities"} ne "") {
									my $new_respons = $auth_params{$cntr . "-responsibilities"};
						
									if ( length($new_respons) <= 48 ) { 
										push @update_clause_bts, "responsibilities=?";
										push @new_vals, $new_respons;	
									}
									else {
										push @{$errors{$adm}}, "Too many responsibilities were selected. Check to make sure no responsibilities were entered multiple times. If you still get this error, notify the developer.";	
									}
								}
								#dorm
								if (exists $auth_params{$cntr . "-dorm"}) {
									my $new_dorm = $auth_params{$cntr . "-dorm"};
							
									if (exists $valid_dorms{uc($new_dorm)}) { 
										if ( length($new_dorm) <= 48 ) { 
											push @update_clause_bts, "house_dorm=?";
											push @new_vals, $new_dorm;	
										}
										else {
											push @{$errors{$adm}}, "The dorm name is too long. To fix this issue, ask the administrator to change its name by changing the 'dorms' variable.";
										}
									}
									else {
										push @{$errors{$adm}}, "The dorm entered is not one of those configured by the administrator. Valid dorms are: $valid_dorms_str. If you want to add this dorm to the list, ask the administrator to change the 'dorms' system variable.";
									}
								}
								if ($seen_s_name and $seen_o_names) {
									my $set_clause = join (',', @update_clause_bts);
									my $prep_stmt = $con->prepare("REPLACE INTO `$roll` SET $set_clause");
									if ($prep_stmt) {
										my $rc = $prep_stmt->execute(@new_vals);
										unless ($rc) {
											print STDERR "Could not execute REPLACE INTO $roll stmt: ", $prep_stmt->errstr, "\n";
										}
									}
									else {
										print STDERR "Could not prepare REPLACE INTO $roll stmt: ", $prep_stmt->errstr, "\n";
									}
									
									$adds{$adm}++;
								}
								else {
									push @{$errors{$adm}}, "For a record to be accepted, it must have both the 'surname' and 'other names' fields provided.";
								}
							}
						}
					}
					#update the adms table
					my @values_bts;
					my @values;
					foreach (keys %adds) {
						push @values_bts, "(?,?)";
						push @values, $_, $roll;
					}
					if (@values_bts) {
						my $values_str = join(',', @values_bts);
						my $prep_stmt2 = $con->prepare("REPLACE INTO adms VALUES $values_str");	
						if ($prep_stmt2) {
							my $rc = $prep_stmt2->execute(@values);
							unless ($rc) {
								print STDERR "Could not execute REPLACE INTO adms stmt: ", $prep_stmt2->errstr, "\n";
							}
						}
						else {
							print STDERR "Could not prepare REPLACE INTO adms stmt: ", $prep_stmt2->errstr, "\n";
						}	 
					}
					$con->commit();
					#log actions
					
					my @today = localtime;
					my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

						
					open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        				if ($log_f) {
						my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
						flock ($log_f, LOCK_EX) or print STDERR "Could not log delete student rol for $id due to flock error: $!$/"; 
						seek ($log_f, 0, SEEK_END);
						#edits
						for my $stud_adm (keys %edits) {
							my $changed_fields = join(',',  @{$edits{$stud_adm}});
		 					print $log_f "$id STUDENT UPDATE $stud_adm ($changed_fields) $time\n";
						}
						#adds
						for my $student_adm (keys %adds) {
							print $log_f "$id STUDENT ADD $student_adm $time\n";
						}
						flock ($log_f, LOCK_UN);
                				close $log_f;
        				}
					else {
						print STDERR "Could not log delete student roll for $id: $!\n";
					}
					#display_for_editing with %errors passed in
					for my $adm_err (keys %errors) {
						delete $errors{$adm_err} unless ( scalar(@{$errors{$adm_err}}) );
					}
					display_for_editing($roll, 1);
				}
			}
			else {
				$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Edit Student Roll</title>
</head>
<body>
$header
<span style="color: red">Your request was not sent with the appropriate authorization tokens!</span> To get fresh tokens, reload the Edit Roll page.
};
			}
		}
		else {
				$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Edit Student Roll</title>
</head>
<body>
$header
<span style="color: red">Sorry, you are not authorized to edit this student roll!(a)</span> 
};
		}
	}
	else {
		#user has requested a specific roll
		#display a form to edit this data 
		if (defined $roll) {
			if (exists $authd_rolls{$roll}) {
				display_for_editing($roll);
			}
			else {
				$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Edit Student Roll</title>
</head>
<body>
$header
<span style="color: red">Sorry, you are not authorized to edit this student roll!(b)</span> 
};
			}
		}

		#Just display a list of student rolls for which the user has appropriate privileges
		else {
			my $authd_to_edit = '';
			if ($num_authd_rolls == 1) {
				my ($class, $grad_yr);
				my $t_name = (keys %authd_rolls)[0];
				my %authd_kv = %{$authd_rolls{$t_name}};
				$authd_to_edit = qq!You are authorized to edit <a href="/cgi-bin/editroll.cgi?roll=$t_name">$authd_kv{"class"} (Graduating class of $authd_kv{"grad_year"})</a>!;
			}
			else {
				$authd_to_edit = 'Which of the following student rolls would you like to edit?:<ol>';
				for my $roll (sort { ${$authd_rolls{$a}}{"class"} cmp ${$authd_rolls{$b}}{"class"} } keys %authd_rolls) {
					my %authd_kv = %{$authd_rolls{$roll}};
					$authd_to_edit .= qq!<li><a href="/cgi-bin/editroll.cgi?roll=$roll">$authd_kv{"class"} (Graduating class of $authd_kv{"grad_year"})</a>!;
				}
					$authd_to_edit .= "</ol>";
			}
			$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Edit Student Roll</title>
</head>
<body>
$header
$authd_to_edit 
};
		}
	}
	$session{"confirm_code"} = $conf_code;
}
else {
		$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Edit Student Roll</title>
</head>
<body>
$header
<em>Sorry. There are no student rolls for you to edit</em>. This could be because:<ol><li>You are not authorized to edit any student roll. To fix this, get an up-to-date token with the appropriate privileges from the administrator. or<li>There are no student rolls created yet. Would you like to <a href="/cgi-bin/createroll.cgi">create a student roll</a> now? 
</body>
</html>	
};
}


print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

if ($update_session) { 
	my @new_sess_array = ();
	for my $sess_key (keys %session) {	
		push @new_sess_array, $sess_key."=".$session{$sess_key};        
	}
	my $new_sess = join ('&',@new_sess_array);
	print "X-Update-Session: $new_sess\r\n";
}

print "\r\n";
print $content;
$con->disconnect();

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub display_for_editing {
	my $edit_table = '';
	my $table = undef;
	unless (@_) {
		return '';
	}
	$table = $_[0];
	my $feedback = '';
	#Some changes have been made to the student roll 
	if (@_ > 1 and $_[1] eq "1") {
		#...and errors were spotted
		if (scalar(keys %errors) > 0) {
			$feedback .= 'Some issues were noted with the data you sent over:<ol>';
			foreach (sort {$errors{$a} <=> $errors{$b}} keys %errors) {
				my @issues = @{$errors{$_}};
				if (@issues) { 
					$feedback .= "<li>$_<ul>";
					for my $issue (@issues) {
						$feedback .= "<li>$issue";
					}
					$feedback .= "</ul>";
				}
			}
			$feedback .= "</ol>";
		}
	}
	$edit_table .= 
		qq{
<form action="/cgi-bin/editroll.cgi?roll=$roll&act=edit" enctype="multipart/form-data" method="POST">
<input type="hidden" name="confirm_code" value="$conf_code">
<table border="1" cellspacing="2%" style="font-size: 12px; border: 4px black solid; border-spacing: 3pt">
<thead><th><input type="checkbox" id="check-all" onclick="_check_all()"><th><th>Adm no.<th>Surname<th>Other name(s)<th>Picture<th>Marks at admission<th>Subjects<th>Clubs/Societies<th>Games/Sports<th>Reponsibilities<th>$house_label
<tbody>
};
	my $class_size = ${$authd_rolls{$table}}{"size"};
	my $cntr = 0;
	my $longest_subj = 0;
	#$con should be open after reading the student_rolls tables
	#when  checking privileges 
	unless ($con) {
		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});		
	}
	if ($con) {
		my $valid_subjects = 'English,Kiswahili,Mathematics,Chemistry,Physics,Biology,Geography,History and Government,Christian Religious Education,Computers,Business Studies,Agriculture,Art & Design';
		my $valid_dorms = '';
		
		my $prep_stmt = $con->prepare("SELECT id,value FROM vars WHERE id='1-subjects' OR id='1-dorms' LIMIT 2");
		if ($prep_stmt) {
			my $rc = $prep_stmt->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt->fetchrow_array()) {
					if ($rslts[0] eq "1-subjects") {
						$valid_subjects = $rslts[1];	
					}
					elsif ($rslts[0] eq "1-dorms") {
						$valid_dorms = $rslts[1];
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM vars: ", $prep_stmt->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM vars: ", $prep_stmt->errstr, $/;  
		}
		my @subjects_list = split/,/, $valid_subjects;
		foreach (@subjects_list) {
			my $len = length($_);
			if ($len > $longest_subj) {
				$longest_subj = $len;
			}
		}
		my $subjects_width = (($longest_subj * 12 ) + 5) . "px";
		my @dorms_list = split/,/, $valid_dorms;
		my %compulsory_list = ("english" => 1, "kiswahili" => 1, "mathematics" => 1, "chemistry" => 1);
		
		my $_subjects = qq{<div style="height: 100px;width: $subjects_width;border: 1px black solid;overflow-y: scroll">};
					
		for my $subject (@subjects_list) {
			if (exists $compulsory_list{lc($subject)}) {
				$_subjects .= 
				qq{<input checked="1" type="checkbox" name="cntr-subject-$subject" value="$subject"><label>$subject</label><br>};
			}
			else {
				$_subjects .= 
				qq{<input type="checkbox" name="cntr-subject-$subject" value="$subject"><label>$subject</label><br>};
			}
		}
		$_subjects .= '</div>';

		my $clubs = 
qq{
<div style="width: 200px; height: 20px; border: solid grey 2px;">

<select id="pre_set_clubs" style="width: 200px; height: 20px; position: absolute; border: none; margin: 0; font-size: 14px" onclick="get_selection('pre_set_clubs', 'user_set_club')">
<option value="Debating Club">Debating Club</option>
<option value="Drama">Drama</option>
<option value="Environmental Club">Environmental Club</option>
<option value="Home Science Club">Home Science Club</option>
<option value="Journalism">Journalism</option>
<option value="Music">Music</option>
<option value="Rangers/Scouts">Rangers/Scouts</option>
<option value="Young Farmers">Young Farmers</option>
<option value="Law Club">Law Club</option>
<option value="Red Cross/St. John's Ambulance">Red Cross/St. John's Ambulance</option>
<option value="Science Club">Science Club</option>
<option value="UNESCO">UNESCO</option>
<option value="Wildlife">Wildlife</option>
</select>

<input type="text" id="user_set_club" style="width: 185px; height: 18px; position: absolute; border: none; font-size: 14px" name="cntr-clubn" value="">

</div>
};

		my $societies =
qq{
<div style="width: 200px; height: 20px; border: solid grey 2px;overflow-y: scroll">

<select id="pre_set_societies" style="width: 200px; height: 20px; position: absolute; border: none; margin: 0; font-size: 14px" onclick="get_selection('pre_set_societies', 'user_set_society')">
<option value="C.U">C.U</option>
<option value="Y.C.S">Y.C.S</option>
<option value="Muslim">Muslim</option>
</select>
<input type="text" id="user_set_society" style="width: 185px; height: 18px; position: absolute; border: none; font-size: 14px" name="cntr-society" value="">
</div>
};

		my $_games_sports =
qq{
<div style="width: 200px; height: 20px; border: solid grey 2px;">

<select id="pre_set_games" style="width: 200px; height: 20px; position: absolute; border: none; margin: 0; font-size: 14px" onclick="get_selection('pre_set_games', 'user_set_game')">
<option value="Athletics">Athletics</option>
<option value="Badminton">Badminton</option>
<option value="Basketball">Basketball</option>
<option value="Cricket">Cricket</option>
<option value="Football/Soccer">Football/Soccer</option>
<option value="Golf">Golf</option>
<option value="Handball">Handball</option>
<option value="Hockey">Hockey</option>
<option value="Lawn Tennis">Lawn Tennis</option>
<option value="Netball">Netball</option>
<option value="Rugby">Rugby</option>
<option value="Swimming">Swimming</option>
<option value="Table Tennis">Table Tennis</option>
<option value="Volleyball">Volleyball</option>
</select>

<input type="text" id="user_set_game" style="width: 185px; height: 18px; position: absolute; border: none; font-size: 14px" name="cntr-gamen" value="">

</div>
};

		my $_responsibilities =
qq{
<div style="width: 200px; height: 20px; border: solid grey 2px;">

<select id="pre_set_responsibilities" style="width: 200px; height: 20px; position: absolute; border: none; margin: 0; font-size: 14px" onclick="get_selection('pre_set_responsibilities', 'user_set_responsibility')">
<option value="Student Council">Student Council</option>
<option value="Club Official">Club Official</option>
<option value="Class Monitor">Class Monitor</option>
<option value="Prefect">Prefect</option>
</select>
<input type="text" id="user_set_responsibility" style="width: 185px; height: 18px; position: absolute; border: none; font-size: 14px" name="cntr-responsibilities" value="">
</div>
};

		my $dorm = qq{<input type="text" name="cntr-dorm" value="">};
		if (@dorms_list) {
			$dorm = 
qq{
<div style="width: 200px; height: 20px; border: solid grey 2px;">
<select id="pre_set_dorms" style="width: 200px; height: 20px; position: absolute; border: none; margin: 0; font-size: 14px" onclick="get_selection('pre_set_dorms', 'user_set_dorm')">
};
			foreach (@dorms_list) {
				$dorm .= qq{<option value="$_">$_</option>};
			}
			$dorm .= qq{</select>};
			$dorm .= qq{<input type="text" id="user_set_dorm" style="width: 185px; height: 18px; position: absolute; border: none; font-size: 14px" name="cntr-dorm" value="">};
		}
		
		my $prep_stmt2 = $con->prepare("SELECT adm,s_name,o_names,has_picture,marks_at_adm,subjects,clubs_societies,sports_games,responsibilities,house_dorm FROM `$table` ORDER BY adm ASC");
		if ($prep_stmt2) {
			my $rc = $prep_stmt2->execute();
			if ($rc) {	
				while (my @rslts = $prep_stmt2->fetchrow_array()) {
					++$cntr;			
					my ($adm,$s_name,$o_names,$has_picture,$marks_at_adm,$subjects,$clubs_societies,$games_sports,$responsibilities,$house_dorm) = @rslts;
					my $pict_ico = "/images/red_box.png";
					if (defined $has_picture and $has_picture ne "") {
						if ($has_picture eq "yes") {
							$pict_ico = "/images/green_box.png";
						}
					}
					my @stud_subjects_array = ();
					if (defined $subjects) {
						@stud_subjects_array = split/,/,$subjects;
					}
					my %stud_subjects_hash;
					foreach (@stud_subjects_array) {
						$stud_subjects_hash{$_}++;
					}
					my $subjects_str = '<div style="height: 100px; border: 1px black solid;overflow-y: scroll">';
					
					for my $subject (@subjects_list) {
						if (exists $stud_subjects_hash{$subject}) {
							$subjects_str .= 
						qq{<input type="checkbox" name="$cntr-subject-$subject" value="$subject" checked>$subject<br>};
						}
						else {
							$subjects_str .= 
						qq{<input type="checkbox" name="$cntr-subject-$subject" value="$subject">$subject<br>};
						}
					}
					$subjects_str .= '</div>';
					
					my @stud_clubs_societies_array = ();
					if (defined $clubs_societies) {
						@stud_clubs_societies_array = split/,/,$clubs_societies;
					}

					my @clubs_societies_array = ($societies, $clubs, $clubs);
					my $club_cntr = -1;
					for my $club_society (@clubs_societies_array) {
						++$club_cntr;	
						#already seen the society, now seeing clubs
						if ($club_cntr > 0) {
							$club_society =~ s/user_set_club/$cntr-user_set_club$club_cntr/g;
							$club_society =~ s/pre_set_clubs/$cntr-pre_set_clubs$club_cntr/g;
							$club_society =~ s/name="cntr-clubn"/name="$cntr-club$club_cntr"/;		
						}
						else {
							$club_society =~ s/name="cntr-/name="$cntr-/;
							$club_society =~ s/user_set_society/$cntr-user_set_society/g;
							$club_society =~ s/pre_set_societies/$cntr-pre_set_societies/g;
						}
						my $stud_club_society = pop(@stud_clubs_societies_array);

						#replace value="" with the currently set club/society
						if (defined $stud_club_society) {
							$club_society =~ s/value=""/value="$stud_club_society"/;
						}
					}
					my $clubs_str = join('<br>',@clubs_societies_array);

					my @stud_games_sports_array = ();
					if (defined $games_sports) {
						@stud_games_sports_array = split/,/,$games_sports;
					}
					my @games_sports_array = ($_games_sports,$_games_sports);
					my $game_cntr = 0;
					for my $game_sport (@games_sports_array) {
						++$game_cntr;
						$game_sport =~ s/name="cntr-gamen/name="$cntr-game$game_cntr/;	
						$game_sport =~ s/user_set_game/$cntr-user_set_game$game_cntr/g;
						$game_sport =~ s/pre_set_games/$cntr-pre_set_games$game_cntr/g;
						my $stud_game_sport = pop(@stud_games_sports_array);

						#replace value="" with the currently set club/society
						if (defined $stud_game_sport) {
							$game_sport =~ s/value=""/value="$stud_game_sport"/;
						}
					}
					my $games_str = join('<br>', @games_sports_array);

					my $responsibility_str = $_responsibilities;
					$responsibility_str =~ s/name="cntr-responsibilities/name="$cntr-responsibilities/;

					$responsibility_str =~ s/user_set_responsibility/$cntr-user_set_responsibility/g;
					$responsibility_str =~ s/pre_set_responsibilities/$cntr-pre_set_responsibilities/g;

					if (defined $responsibilities and $responsibilities ne "") {
						$responsibility_str =~ s/value=""/value="$responsibilities"/;
					}

					my $dorm_str = $dorm;
					$dorm_str =~ s/name="cntr-dorm"/name="$cntr-dorm"/;
				
					$dorm_str =~ s/user_set_dorm/$cntr-user_set_dorm/g;
					$dorm_str =~ s/pre_set_dorms/$cntr-pre_set_dorms/g;
					if (defined $house_dorm and $house_dorm ne "") {
						$dorm_str =~ s/value=""/value="$house_dorm"/;
					}
					$edit_table .=
					qq{<tr><td><input type="checkbox" id="$cntr-check" onchange="add_adm('$cntr')"><td>$cntr.<td><input type="text" id="$cntr-adm" name="$cntr-adm" value="$adm" size="10" maxlength="5" readonly><td><input type="text" id="$cntr-s_name" name="$cntr-s_name" value="$s_name" size="15" maxlength="16"><td><input type="text" id="$cntr-o_names" name="$cntr-o_names" value="$o_names" size="30" maxlength="64"><td style="text-align: center"><img src="$pict_ico" height="14px" width="14px"><input type="file" name="$cntr-picture"><td><input type="text" name="$cntr-marks_at_adm" value="$marks_at_adm" size="5" maxlength="5"><td>$subjects_str<td>$clubs_str<td>$games_str<td>$responsibility_str<td>$dorm_str};
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM $table: ", $prep_stmt2->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM $table: ", $prep_stmt->errstr, $/;  
		}
		#append blanks to remainder of form
		$cntr++;

		for (; $cntr <= $class_size; $cntr++) {
			my $rem_subjects_str = $_subjects;
			$rem_subjects_str =~ s/name="cntr-/name="$cntr-/g;
		
			my @clubs_societies_array = ($societies, $clubs, $clubs);
			my $club_cntr = -1;
			for my $club_society (@clubs_societies_array) {
				++$club_cntr;

				#already seen the society, now seeing clubs
				if ($club_cntr > 0) {
 					$club_society =~ s/user_set_club/$cntr-user_set_club$club_cntr/g;
					$club_society =~ s/pre_set_clubs/$cntr-pre_set_clubs$club_cntr/g;

					$club_society =~ s/name="cntr-clubn"/name="$cntr-club$club_cntr"/;
				}
				else {
					$club_society =~ s/name="cntr-/name="$cntr-/;
					$club_society =~ s/user_set_society/$cntr-user_set_society/g;
					$club_society =~ s/pre_set_societies/$cntr-pre_set_societies/g;
				}	
			}
			my $rem_clubs_str = join('<br>',@clubs_societies_array);

				
			my @games_sports_array = ($_games_sports,$_games_sports);
			my $game_cntr = 0;
			for my $game_sport (@games_sports_array) {
				++$game_cntr;
				$game_sport =~ s/user_set_game/$cntr-user_set_game$game_cntr/g;
				$game_sport =~ s/pre_set_games/$cntr-pre_set_games$game_cntr/g;
				$game_sport =~ s/name="cntr-gamen/name="$cntr-game$game_cntr/;
			}
			my $rem_games_str = join('<br>', @games_sports_array);

			my $rem_responsibility_str = $_responsibilities;
			$rem_responsibility_str =~ s/user_set_responsibility/$cntr-user_set_responsibility/g;
			$rem_responsibility_str =~ s/pre_set_responsibilities/$cntr-pre_set_responsibilities/g;
			$rem_responsibility_str =~ s/name="cntr-responsibilities/name="$cntr-responsibilities/;


			my $rem_dorm_str = $dorm;
			$rem_dorm_str =~ s/user_set_dorm/$cntr-user_set_dorm/g;
			$rem_dorm_str =~ s/pre_set_dorms/$cntr-pre_ser_dorms/g;
			$rem_dorm_str =~ s/name="cntr-dorm"/name="$cntr-dorm"/;

			$edit_table .=
qq{<tr><td><input type="checkbox" id="$cntr-check" onchange="add_adm('$cntr')"><td>$cntr.<td><input type="text" id="$cntr-adm" name="$cntr-adm" value="" size="10" maxlength="5"><td><input type="text" name="$cntr-s_name" id="$cntr-s_name" value="" size="15" maxlength="16"><td><input type="text" name="$cntr-o_names"  id="$cntr-o_names" value="" size="30" maxlength="64"><td style="text-align: center"><img alt="No pic" src="/images/red_box.png"><input type="file" name="$cntr-picture"><td><input type="text" name="$cntr-marks_at_adm" value="" size="5" maxlength="5"><td>$rem_subjects_str<td>$rem_clubs_str<td>$rem_games_str<td>$rem_responsibility_str<td>$rem_dorm_str};
		}
		
		$edit_table .= qq{</table><p><table><tr><td><input disabled type="button" id="delete" name="delete" value="Delete Selected" onclick="delete_()"><input disabled type="button" id="move" name="move" value="Move Selected" onclick="move_()"><td><input type="submit" name="Save" value="Save Changes"></table></form>};	
	}
	else {
		print STDERR "Cannot connect: $con->strerr$/";
	}
	my $class   = ${$all_rolls{$roll}}{"class"};
	my $grad_yr = ${$all_rolls{$roll}}{"grad_year"};

	my @all_rolls_js_bts;
	for my $roll_1 ( keys %all_rolls) {
		next if ($roll eq $roll_1);
		push @all_rolls_js_bts, qq!"$roll_1": "${$all_rolls{$roll_1}}{"class"}(Class of ${$all_rolls{$roll_1}}{"grad_year"})"!;
	}
	my $all_rolls_js_str = "{" . join(", ", @all_rolls_js_bts) . "}"; 
		
	$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Edit Student Roll</title>
<script type="text/javascript">
var row_cnt = $class_size;
var checked_adms = [];
var reduce_size_by = 0;
var checked_cnt = 0;
var rolls = $all_rolls_js_str;

function get_selection(from, to) {
	var selection = document.getElementById(from).value;
	document.getElementById(to).value = selection;
}

function add_adm(cntr) {	
	var checked = document.getElementById(cntr + "-check").checked;
	var adm_no = document.getElementById(cntr + "-adm").value;
	if (checked) {
		checked_cnt++;
		if (adm_no !== "") {
			var s_name = document.getElementById(cntr + "-s_name").value;
			var o_names = document.getElementById(cntr + "-o_names").value;
			var name = "";
			if (s_name !== "") {
				name += "(" + s_name;
				if (o_names !== "") {
					name += ", " + o_names; 
				}
				name += ")";
			}
			checked_adms.push({stud_adm: adm_no, stud_name: name});
		}
		reduce_size_by++;
		document.getElementById("delete").disabled = false;
		document.getElementById("move").disabled = false;
	}
	else {
		if (--checked_cnt <= 0) {
			document.getElementById("delete").disabled = true;
			document.getElementById("move").disabled = true;
		}
		if (adm_no !== "") {
			for (var i = 0; i < checked_adms.length; i++) {
				if (checked_adms[i].stud_adm === adm_no) {
					checked_adms.splice(i, 1);
					break;
				}
			}
		}
		reduce_size_by--;
	}
}

function _check_all() {
	var new_state = document.getElementById("check-all").checked;
	for (var i = 1; i <= row_cnt; i++) {
		document.getElementById(i + "-check").checked = new_state;
		add_adm(i);
	}
}

function delete_() {
	if (reduce_size_by > 0) { 
		var new_size = row_cnt - reduce_size_by;	
		var new_content = "";
		var studs_to_del = '';
		var new_loc = "/cgi-bin/editroll.cgi?roll=$roll"; 
		if (new_size == 0) {
			new_content += "<em>Clicking confirm will delete this student roll. NOTE: this action cannot be undone.</em>";
			studs_to_del = '*';
		}
		else {
			new_content += "<em>Clicking confirm will reduce the size of this student roll to " + new_size + " students.</em>";
			var num_dels = checked_adms.length;	
			if (num_dels > 0) {
				var plurality = "entries";
				if (num_dels == 1) {
					plurality = "entry";
				}
				new_content += " The following " + plurality + " will be deleted:<ul>";
				var adms = [];
				for (var j = 0; j < num_dels; j++) { 
					new_content += "<li>" + checked_adms[j].stud_adm + " " + checked_adms[j].stud_name;
					adms.push(checked_adms[j].stud_adm);
				}
				studs_to_del = adms.join(',');
				new_content += "</ul>";
			}
		}
		new_content += "<FORM action='/cgi-bin/editroll.cgi?roll=$roll&act=delete' method='POST'>";
 		new_content += "<input type='hidden' name='confirm_code' value='$conf_code'>";	
		new_content += "<input type='hidden' name='studs_to_del' value='" + studs_to_del + "'>";
		new_content += "<input type='hidden' name='reduce_by' value='" + reduce_size_by + "'>";
		new_content += "<table><tr><td><input type='submit' name='confirm' value='Confirm'>";
		new_content += "<td><input type='button' name='cancel' value='Cancel' onclick='window.location.href=\\"/cgi-bin/editroll.cgi?roll=$roll\\"'>";
		new_content += "</table>";
		document.getElementById("edit_table").innerHTML = new_content;	
	}
}

function _add() {
	var new_content = "<form action='/cgi-bin/editroll.cgi?roll=$roll&act=add' method='post'>";
	new_content += "<input type='hidden' name='confirm_code' value='$conf_code'>";
	new_content += "<table><tr>";
	new_content += "<td><label for='num_adds'>Number of Students to Add</label>";
	new_content += "<td><input type='text' name='num_adds' value=''>";
	new_content += "</table><table>";
	new_content += "<tr><td><input type='submit' name='add' value='Add Students'>";
	new_content += "<td><input type='submit' name='cancel' value='Cancel' onclick='window.location.href=\\"/cgi-bin/editroll.cgi?roll=$roll\\"'>";
	new_content += "</table>"; 
	document.getElementById("edit_table").innerHTML = new_content;	
}

function move_() {
	var num_moves = checked_adms.length;	

	if (num_moves > 0) {

		var plurality = "students";
		if (num_moves == 1) {
			plurality = "student";
		}

		var new_content = "<FORM action='/cgi-bin/editroll.cgi?roll=$roll&act=move' method='POST'>";
		new_content += "<INPUT type='hidden' name='confirm_code' value='$conf_code'>";
		new_content += "<TABLE><TR><TD><LABEL>Which class would you like to move the " + plurality + " to?</LABEL>";

		new_content += "<TD><SELECT name='move_to'>";

		for (roll in rolls) {
			new_content += "<OPTION value='" + roll + "'>" + rolls[roll] + "</OPTION>";
		}

		new_content += "</SELECT>";
 
		new_content += "<TR><TD colspan='2'>The following " + plurality + " will be moved:<ul>";
		var adms = [];

		for (var j = 0; j < num_moves; j++) { 
			new_content += "<li>" + checked_adms[j].stud_adm + " " + checked_adms[j].stud_name;
			adms.push(checked_adms[j].stud_adm);
		}
	
		new_content += "</ul>";
	
		new_content += "<TR><TD><INPUT type='submit' name='move' value='Move'><TD>&nbsp;</TABLE>";
		studs_to_move = adms.join(',');
		new_content += "<INPUT type='hidden' name='studs_to_move' value='" + studs_to_move + "'>"; 
		new_content += "</FORM>";
		document.getElementById("edit_table").innerHTML = new_content;	
	}
}

</script>
</head>
<body>
$header
<p><h4><span style="text-decoration: underline">$class(Graduating class of $grad_yr)</span></h4></p>
<div id="edit_table">
<p>
$feedback
</p>
<p><input type="button" name="add" value="Add New Student(s)" onclick="_add()"> 
$edit_table
</div>
</body>
</html>
}; 
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}
